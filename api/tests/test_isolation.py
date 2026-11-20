"""AC3: two-user isolation. User B gets 404 (never 403, never data) on every `{id}`-addressed
route of user A, on both the token path and the API-key path. The route table is checked against
the committed OpenAPI so a new id route cannot ship without isolation coverage.
"""

import json
from pathlib import Path

import httpx
import pytest
from audio_helpers import MAGIC, StubTools

from onolys_api.adapters import Adapters, FakeEvaluation, FakeStt
from onolys_api.app import create_app
from onolys_api.repo.fake import FakeRepo

pytestmark = pytest.mark.integration
OPENAPI = Path(__file__).resolve().parents[1] / "openapi.json"
CARD = {"change_goal": "g", "notes": "n"}
ALICE = {"Authorization": "Bearer test:alice"}
BOB = {"Authorization": "Bearer test:bob"}

# (method, path template) -> request json body (None = no body). Every op with a path param.
ID_ROUTES: dict[tuple[str, str], dict | None] = {
    ("get", "/v1/runs/{run_id}"): None,
    ("get", "/v1/sessions/{id}"): None,
    ("delete", "/v1/sessions/{id}"): None,
    ("get", "/v1/sessions/{id}/audio"): None,
    ("post", "/v1/sessions/{id}/audio"): {"content_type": "audio/wav", "size_bytes": 100},
    ("post", "/v1/sessions/{id}/audio/complete"): None,
    ("get", "/v1/sessions/{id}/rating"): None,
    ("put", "/v1/sessions/{id}/rating"): {"final": True, "card": CARD},
    ("get", "/v1/sessions/{id}/reports"): None,
    ("get", "/v1/sessions/{id}/reports/{version}"): None,
    ("get", "/v1/sessions/{id}/runs"): None,
    ("post", "/v1/sessions/{id}/runs"): {},
    ("get", "/v1/sessions/{id}/speakers"): None,
    ("post", "/v1/sessions/{id}/speakers/confirm"): {"clinician_speaker": "S1"},
    ("get", "/v1/sessions/{id}/transcript"): None,
}


def test_every_id_route_is_covered():
    spec = json.loads(OPENAPI.read_text())
    actual = {
        (m, p)
        for p, ops in spec["paths"].items()
        if "{" in p
        for m in ops
        if m in {"get", "put", "post", "delete", "patch"}
    }
    assert actual == set(ID_ROUTES), (
        f"uncovered: {sorted(actual - set(ID_ROUTES))}; stale: {sorted(set(ID_ROUTES) - actual)}"
    )


@pytest.fixture
async def world(settings, blobs):
    repo = FakeRepo(blobs)
    app = create_app(
        settings,
        repo=repo,
        blobs=blobs,
        audio_tools=StubTools(),
        adapters=Adapters(stt=FakeStt(), evaluation=FakeEvaluation()),
    )
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        sid = (await c.post("/v1/sessions", json={"title": "a"}, headers=ALICE)).json()["session"][
            "id"
        ]
        up = (
            await c.post(
                f"/v1/sessions/{sid}/audio",
                json={"content_type": "audio/wav", "size_bytes": len(MAGIC["wav"])},
                headers=ALICE,
            )
        ).json()
        await c.put(
            up["upload_url"].removeprefix("http://localhost:8000"),
            content=MAGIC["wav"],
            headers=up["required_headers"],
        )
        await c.post(f"/v1/sessions/{sid}/audio/complete", headers=ALICE)
        app.state.queue.drain()
        await c.post(
            f"/v1/sessions/{sid}/speakers/confirm", json={"clinician_speaker": "S1"}, headers=ALICE
        )
        await c.put(f"/v1/sessions/{sid}/rating", json={"final": True, "card": CARD}, headers=ALICE)
        app.state.queue.drain()
        sess = (await c.get(f"/v1/sessions/{sid}", headers=ALICE)).json()
        assert sess["status"] == "report_ready", sess
        run_id = (await c.get(f"/v1/sessions/{sid}/runs", headers=ALICE)).json()["items"][0][
            "run_id"
        ]
        bob_key = (await c.post("/v1/api-key", headers=BOB)).json()["api_key"]
        yield c, sid, run_id, {"X-API-Key": bob_key}


def fill(path: str, sid: str, run_id: str) -> str:
    return path.replace("{id}", sid).replace("{run_id}", run_id).replace("{version}", "1")


@pytest.mark.parametrize("auth", ["token", "api_key"])
async def test_every_id_route_is_404_for_another_user(world, auth):
    c, sid, run_id, bob_key = world
    headers = BOB if auth == "token" else bob_key
    for (method, template), body in ID_ROUTES.items():
        path = fill(template, sid, run_id)
        r = await c.request(method, path, json=body, headers=headers)
        assert r.status_code == 404, (auth, method, path, r.status_code, r.text)
        assert r.json()["status"] == 404 and r.json()["request_id"]
        assert sid not in r.text.replace(path, "") and run_id not in r.text.replace(path, "")
    # nothing of A's was touched by B's delete/put/post attempts
    assert (await c.get(f"/v1/sessions/{sid}", headers=ALICE)).json()["status"] == "report_ready"
    assert (await c.get(f"/v1/sessions/{sid}/reports/1", headers=ALICE)).status_code == 200
    assert (await c.get(f"/v1/sessions/{sid}/reports/2", headers=ALICE)).status_code == 404
    assert len((await c.get(f"/v1/sessions/{sid}/runs", headers=ALICE)).json()["items"]) == 1


async def test_bob_never_sees_alices_session_in_lists(world):
    c, sid, run_id, bob_key = world
    for headers in (BOB, bob_key):
        assert (await c.get("/v1/sessions", headers=headers)).json()["items"] == []
