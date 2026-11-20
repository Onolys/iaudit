"""AC2: the complete stub flow over HTTP (fake repo/blobs/adapters, in-memory queue).

Both rating orders (before and after transcription finishes), report v1 then v2, and
`GET /sessions` listing a done, a failed and an in-flight session together.
"""

import uuid
from dataclasses import replace

import httpx
import pytest
from audio_helpers import MAGIC, StubTools

from onolys_api.app import create_app
from onolys_api.repo.fake import FakeRepo

pytestmark = pytest.mark.integration
CARD = {"change_goal": "g", "notes": "n"}
ROUTES = (
    "cheap: &s {litellm_id: anthropic/x, api_key_env: K}\nmid: *s\nstrong: *s\n"
    "paudit_code: {alias: mid}\npaudit_globals: {alias: mid}\ntips: {alias: mid}\n"
    "presets:\n  default: {routes: {}}\n  fast: {routes: {}}\n"
)


class Flow:
    def __init__(self, app, client) -> None:
        self.app, self.c = app, client
        self.h = {"Authorization": f"Bearer test:u{uuid.uuid4().hex[:10]}"}

    def drain(self) -> None:
        self.app.state.queue.drain()

    async def get(self, path: str) -> dict:
        r = await self.c.get(f"/v1{path}", headers=self.h)
        assert r.status_code == 200, (path, r.text)
        return r.json()

    async def create(self, title: str | None = None) -> str:
        r = await self.c.post("/v1/sessions", json={"title": title}, headers=self.h)
        assert r.status_code == 202
        return r.json()["session"]["id"]

    async def upload(self, sid: str) -> None:
        up = (
            await self.c.post(
                f"/v1/sessions/{sid}/audio",
                json={"content_type": "audio/wav", "size_bytes": len(MAGIC["wav"])},
                headers=self.h,
            )
        ).json()
        put = await self.c.put(
            up["upload_url"].removeprefix("http://localhost:8000"),
            content=MAGIC["wav"],
            headers=up["required_headers"],
        )
        assert put.status_code == 200
        done = await self.c.post(f"/v1/sessions/{sid}/audio/complete", headers=self.h)
        assert done.status_code == 202

    async def confirm(self, sid: str) -> None:
        r = await self.c.post(
            f"/v1/sessions/{sid}/speakers/confirm", json={"clinician_speaker": "S1"}, headers=self.h
        )
        assert r.status_code == 202, r.text

    async def rate(self, sid: str) -> None:
        r = await self.c.put(
            f"/v1/sessions/{sid}/rating", json={"final": True, "card": CARD}, headers=self.h
        )
        assert r.status_code in (200, 202), r.text


@pytest.fixture
async def flow(settings, blobs, tmp_path):
    routes = tmp_path / "routes.yaml"
    routes.write_text(ROUTES)
    (tmp_path / "stt_providers.yaml").write_text(
        "providers:\n  base: {provider: p1, model: m1}\ndefault: base\nby_language: {}\n"
    )
    app = create_app(
        replace(settings, routes_file=str(routes), adapters="stub"),
        repo=FakeRepo(blobs),
        blobs=blobs,
        audio_tools=StubTools(),
    )
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        yield Flow(app, c)


async def test_complete_flow_over_http_both_rating_orders(flow):
    # Order 1: the card is final BEFORE transcription finishes; speaker confirm starts the run.
    s1 = await flow.create("rating first")
    s = await flow.get(f"/sessions/{s1}")
    assert s["status"] == "created" and s["flags"]["rating_submitted"] is False
    await flow.rate(s1)
    await flow.upload(s1)
    assert (await flow.get(f"/sessions/{s1}"))["status"] == "validating"
    flow.drain()
    s = await flow.get(f"/sessions/{s1}")
    assert s["status"] == "awaiting_input"
    assert s["flags"] == {"transcript_ready": True, "speaker_confirmed": False,
                          "rating_submitted": True, "has_rating": True}  # fmt: skip
    await flow.confirm(s1)
    assert (await flow.get(f"/sessions/{s1}"))["status"] == "running"
    flow.drain()
    s = await flow.get(f"/sessions/{s1}")
    assert (s["status"], s["progress"], s["latest_report_version"]) == ("report_ready", 100, 1)

    # Order 2: the card is final AFTER transcription; the final PUT starts the run.
    s2 = await flow.create("rating last")
    await flow.upload(s2)
    flow.drain()
    await flow.confirm(s2)
    assert (await flow.get(f"/sessions/{s2}"))["status"] == "awaiting_input"
    await flow.rate(s2)
    assert (await flow.get(f"/sessions/{s2}"))["status"] == "running"
    flow.drain()
    assert (await flow.get(f"/sessions/{s2}"))["status"] == "report_ready"

    # Second POST /runs creates v2 and keeps v1; both resolve.
    r = await flow.c.post(f"/v1/sessions/{s1}/runs", json={}, headers=flow.h)
    assert r.status_code == 202
    assert (await flow.get(f"/sessions/{s1}"))["status"] == "running"
    flow.drain()
    v1 = await flow.get(f"/sessions/{s1}/reports/1")
    v2 = await flow.get(f"/sessions/{s1}/reports/2")
    assert (v1["version"], v2["version"]) == (1, 2) and v1["run_id"] != v2["run_id"]
    assert v2["run_id"] == r.json()["run_id"]
    assert (await flow.get(f"/sessions/{s1}"))["latest_report_version"] == 2
    listed = {i["id"]: i for i in (await flow.get("/sessions"))["items"]}
    assert listed[s1]["latest_report_version"] == 2
    assert listed[s2]["latest_report_version"] == 1


async def test_list_shows_done_failed_and_inflight(flow):
    done = await flow.create("done")
    await flow.upload(done)
    flow.drain()
    await flow.confirm(done)
    await flow.rate(done)
    flow.drain()
    r = await flow.c.post(f"/v1/sessions/{done}/runs", json={}, headers=flow.h)
    assert r.status_code == 202
    flow.drain()

    failed = await flow.create("bad [fail:no_speech]")  # FakeStt magic title
    await flow.upload(failed)
    flow.drain()

    inflight = await flow.create("inflight")
    await flow.upload(inflight)  # validate task queued, not delivered

    items = (await flow.get("/sessions"))["items"]
    by_id = {i["id"]: i for i in items}
    assert set(by_id) == {done, failed, inflight}
    assert (by_id[done]["status"], by_id[done]["latest_report_version"]) == ("report_ready", 2)
    assert (by_id[failed]["status"], by_id[failed]["error_code"]) == ("failed", "no_speech")
    assert by_id[inflight]["status"] == "validating"
    assert by_id[inflight]["error_code"] is None
