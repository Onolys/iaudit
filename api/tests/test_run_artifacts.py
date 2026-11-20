"""SP09 Task 4 / R4 / AC3: a run through the REAL `Evaluation` adapter over fixtures leaves its
evidence where SP04 says: run artifacts in the blob store, `run_info` on the run doc, `stt` /
`preset` / `code_version` in the report header. A no-rating run has no `eaudit.json`.

No network: the engine's paudit and reasons-audit seams return canned fixture results and the
tips generator returns the fixture tips; everything else (pack, `run_evaluation`, report
assembly, schema validation, the run task) is real. Fake repo and, when
`FIRESTORE_EMULATOR_HOST` is set, the emulator.
"""

import os
import sys
import uuid
from dataclasses import replace
from pathlib import Path

import httpx
import pytest
from audio_helpers import StubTools
from eaudit.models import AuditResponse, Status
from onolys_core.run_info import RunInfo
from onolys_core.transcript import Transcript

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "engines/evaluation/tests"))
from _make_fixtures import inputs  # noqa: E402
from test_run import CARD, ROUTES  # noqa: E402

from onolys_api.adapters import Adapters, FakeStt  # noqa: E402
from onolys_api.adapters.real import RealEvaluation  # noqa: E402
from onolys_api.app import create_app  # noqa: E402
from onolys_api.jobs.transcribe import TRANSCRIPT_ID  # noqa: E402
from onolys_api.repo.fake import FakeRepo  # noqa: E402

pytestmark = pytest.mark.integration
FIX = inputs("full")
FILES = ("paudit", "eaudit", "tips")


@pytest.fixture(autouse=True)
def fixture_engine(monkeypatch):
    from onolys_evaluation import api, tips

    async def fake_paudit(transcript, pack, params, ctx, metrics):
        return FIX["paudit_result"]

    async def fake_eaudit(request, ctx, metrics):
        resp = AuditResponse(request_id="r", status=Status.complete, warnings=[], claims=[])
        return resp, RunInfo(engine="eaudit", code_version="t", preset="default")

    async def fake_tips(*a, **kw):
        return FIX["tips"], []

    monkeypatch.setattr(api, "_run_paudit", fake_paudit)
    monkeypatch.setattr(api, "_run_eaudit", fake_eaudit)
    monkeypatch.setattr(tips, "generate_tips", fake_tips)


class Env:
    def __init__(self, app, client, repo, blobs):
        self.app, self.c, self.repo, self.blobs = app, client, repo, blobs
        self.uid = f"u{uuid.uuid4().hex[:10]}"
        self.h = {"Authorization": f"Bearer test:{self.uid}"}

    async def run(self, rating):
        from audio_helpers import MAGIC

        r = await self.c.post("/v1/sessions", json={"title": None}, headers=self.h)
        sid = r.json()["session"]["id"]
        up = (
            await self.c.post(
                f"/v1/sessions/{sid}/audio",
                json={"content_type": "audio/wav", "size_bytes": len(MAGIC["wav"])},
                headers=self.h,
            )
        ).json()
        await self.c.put(
            up["upload_url"].removeprefix("http://localhost:8000"),
            content=MAGIC["wav"],
            headers=up["required_headers"],
        )
        await self.c.post(f"/v1/sessions/{sid}/audio/complete", headers=self.h)
        self.app.state.queue.drain()
        await self.c.post(
            f"/v1/sessions/{sid}/speakers/confirm", json={"clinician_speaker": "S1"}, headers=self.h
        )
        if rating is not None:
            r = await self.c.put(
                f"/v1/sessions/{sid}/rating", json={"final": True, "card": rating}, headers=self.h
            )
            assert r.status_code in (200, 202), r.text
        else:  # awaiting input: start the run without a rating
            r = await self.c.post(f"/v1/sessions/{sid}/runs", json={}, headers=self.h)
            assert r.status_code == 202, r.text
        # swap in the fixture transcript + its speaker before the run task executes
        self.repo.put_transcript(
            self.uid, sid, TRANSCRIPT_ID, Transcript.model_validate(FIX["transcript"].model_dump())
        )
        self.repo.update_session(self.uid, sid, {"clinician_speaker": "A"})
        self.app.state.queue.drain()
        return sid


@pytest.fixture(params=["fake", "firestore"])
async def env(request, settings, blobs, tmp_path):
    routes = tmp_path / "routes.yaml"
    routes.write_text(ROUTES)
    (tmp_path / "stt_providers.yaml").write_text(
        "providers:\n  base: {provider: p1, model: m1}\ndefault: base\nby_language: {}\n"
    )
    if request.param == "fake":
        repo = FakeRepo(blobs)
    else:
        if not os.environ.get("FIRESTORE_EMULATOR_HOST"):
            pytest.skip("FIRESTORE_EMULATOR_HOST not set")
        from google.auth.credentials import AnonymousCredentials
        from google.cloud import firestore

        from onolys_api.repo.firestore import FirestoreRepo

        repo = FirestoreRepo(
            firestore.Client(project="demo-onolys", credentials=AnonymousCredentials()), blobs
        )
    real = RealEvaluation()  # real LiteLLM client from the preset (no call is made: seams)
    app = create_app(
        replace(settings, routes_file=str(routes)),
        repo=repo,
        blobs=blobs,
        audio_tools=StubTools(),
        adapters=Adapters(stt=FakeStt(), evaluation=real),
    )
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        yield Env(app, c, repo, blobs)


async def test_rated_run_leaves_artifacts_run_info_and_header(env):
    sid = await env.run(CARD)
    assert env.repo.get_session(env.uid, sid).state == "report_ready"
    (run,) = env.repo.list_runs(env.uid, sid)
    assert run.status == "done"
    for name in FILES:
        assert env.blobs.exists(f"{env.uid}/{sid}/runs/{run.run_id}/{name}.json"), name
    assert run.artifacts_prefix.endswith(f"{sid}/runs/{run.run_id}/")
    ri = run.run_info
    assert ri["evaluation"]["code_version"] == "abc123"
    assert ri["evaluation"]["preset"] == "default"
    assert ri["evaluation"]["routes"] and ri["evaluation"]["pack"]["id"]
    assert ri["evaluation"]["pack"]["version"] and ri["evaluation"]["pack"]["hash"]
    assert ri["evaluation"]["prompt_hashes"]
    assert ri["paudit"] and ri["eaudit"]

    r = await env.c.get(f"/v1/sessions/{sid}/reports/1", headers=env.h)
    assert r.status_code == 200
    header = r.json()["report"]["header"]
    assert header["code_version"] == "abc123" and header["preset"] == "default"
    assert header["stt"]["model"] == "synthetic-fixture"
    assert r.json()["report"]["run_info"] == ri


async def test_no_rating_run_has_no_eaudit_artifact(env):
    sid = await env.run(None)
    (run,) = env.repo.list_runs(env.uid, sid)
    assert run.status == "done"
    base = f"{env.uid}/{sid}/runs/{run.run_id}"
    assert env.blobs.exists(f"{base}/paudit.json") and env.blobs.exists(f"{base}/tips.json")
    assert not env.blobs.exists(f"{base}/eaudit.json")
    assert run.run_info["eaudit"] is None
    report = (await env.c.get(f"/v1/sessions/{sid}/reports/1", headers=env.h)).json()["report"]
    assert report["reasons_audit"]["status"] == "skipped"
