"""Stale-status sweeper: jobs/sweep.py and POST /tasks/sweep-stale. Fake clock, no sleeps."""

import json
import logging
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from test_worker import mint, verifier, worker_settings  # noqa: F401 (fixture)

from onolys_api.app import create_app
from onolys_api.jobs import sweep
from onolys_api.jobs.sweep import RULES, sweep_stale
from onolys_api.jobs.transcribe import STT_TIME_LIMIT_S
from onolys_api.repo.fake import FakeRepo
from onolys_api.repo.models import SessionDoc, SessionStatusDoc, StepRecord

pytestmark = pytest.mark.unit
NOW = datetime(2026, 6, 1, 12, 0, tzinfo=UTC)
LIMIT = {r.state: r.limit_s for r in RULES}


def clock():
    return NOW


def mk(repo, sid, state, age_s, uid="u1", step="transcribe"):
    t = NOW - timedelta(seconds=age_s)
    repo.create_session(
        uid, sid,
        SessionDoc(uid=uid, state=state, step=step, created_at=t, updated_at=t,
                   steps={step: StepRecord(status="pending")}),
        SessionStatusDoc(uid=uid, state=state, step=step, progress=20, updated_at=t),
    )  # fmt: skip


@pytest.fixture
def repo(blobs):
    return FakeRepo(blobs)


def test_limits_exceed_the_in_chain_limits():
    assert LIMIT["transcribing"] == STT_TIME_LIMIT_S + sweep.SWEEP_MARGIN_S
    assert LIMIT["transcribing"] > STT_TIME_LIMIT_S and LIMIT["validating"] > 8 * 60


def test_stale_transcribing_is_failed_with_transcription_failed(repo):
    mk(repo, "old", "transcribing", LIMIT["transcribing"] + 1)
    assert sweep_stale(repo, clock) == {"transcribing": 1, "validating": 0}
    s = repo.get_session("u1", "old")
    assert (s.state, s.error.code, s.error.step) == ("failed", "transcription_failed", "transcribe")
    assert s.steps["transcribe"].status == "failed"
    st = repo.get_status("u1", "old")
    assert (st.state, st.error_code, st.progress) == ("failed", "transcription_failed", 20)


def test_stale_validating_is_failed_with_deadline_exceeded(repo):
    mk(repo, "v", "validating", LIMIT["validating"] + 1, step="validate")
    sweep_stale(repo, clock)
    s = repo.get_session("u1", "v")
    assert (s.state, s.error.code, s.error.step) == ("failed", "deadline_exceeded", "validate")


def test_fresh_sessions_are_untouched(repo):
    mk(repo, "live", "transcribing", STT_TIME_LIMIT_S + 5)  # past the chain limit, inside margin
    mk(repo, "new", "transcribing", 30)
    assert sweep_stale(repo, clock) == {"transcribing": 0, "validating": 0}
    assert repo.get_session("u1", "live").state == "transcribing"
    assert repo.get_session("u1", "new").error is None


@pytest.mark.parametrize("state", ["awaiting_input", "failed", "running", "report_ready",
                                   "created", "uploading", "deleting"])  # fmt: skip
def test_other_states_are_untouched_however_old(repo, state):
    mk(repo, "x", state, 10 * 24 * 3600)
    assert sweep_stale(repo, clock) == {"transcribing": 0, "validating": 0}
    assert repo.get_session("u1", "x").state == state


def test_second_sweep_is_a_noop(repo):
    mk(repo, "old", "transcribing", LIMIT["transcribing"] + 1)
    mk(repo, "old2", "transcribing", LIMIT["transcribing"] + 100, uid="u2")
    assert sweep_stale(repo, clock)["transcribing"] == 2
    before = len(repo.status_writes)
    assert sweep_stale(repo, clock)["transcribing"] == 0
    assert len(repo.status_writes) == before
    assert repo.get_session("u2", "old2").error.code == "transcription_failed"


def test_session_that_finished_between_list_and_fail_is_untouched(repo, monkeypatch):
    mk(repo, "race", "transcribing", LIMIT["transcribing"] + 1)
    real = repo.list_stale_sessions

    def list_then_finish(*a, **kw):
        out = real(*a, **kw)  # the sweeper has the stale snapshot ...
        repo.update_session(
            "u1", "race", {"state": "awaiting_input", "transcript_ready": True},
            status={"state": "awaiting_input", "progress": 40},
        )  # ... then the live poll finishes
        return out

    monkeypatch.setattr(repo, "list_stale_sessions", list_then_finish)
    assert sweep_stale(repo, clock)["transcribing"] == 0
    s = repo.get_session("u1", "race")
    assert (s.state, s.error, s.transcript_ready) == ("awaiting_input", None, True)


def test_sweep_logs_ids_and_codes_only(repo, caplog):
    mk(repo, "old", "transcribing", LIMIT["transcribing"] + 1)
    with caplog.at_level(logging.INFO):
        sweep_stale(repo, clock)
    lines = [json.loads(r.getMessage()) for r in caplog.records if r.name.startswith("onolys_api")]
    (f,) = [d for d in lines if d.get("event") == "session_swept"]
    assert (f["status"], f["session_id"], f["error_code"]) == ("failed", "old", "transcription_failed")
    assert "uid" not in f and "u1" not in json.dumps(lines)


# ---- endpoint ----


async def _post(app, headers=None):
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app, raise_app_exceptions=False), base_url="http://t"
    ) as c:
        return await c.post("/tasks/sweep-stale", headers=headers or {})


@pytest.fixture
def app(worker_settings, repo, blobs):  # noqa: F811
    a = create_app(worker_settings, repo=repo, blobs=blobs, oidc_verifier=verifier())
    a.state.runner.clock = clock
    return a


async def test_endpoint_requires_the_invoker_oidc(app, repo):
    mk(repo, "old", "transcribing", LIMIT["transcribing"] + 1)
    assert (await _post(app)).status_code == 401
    assert (await _post(app, {"Authorization": "Bearer junk"})).status_code == 401
    bad = {"Authorization": f"Bearer {mint(aud='https://x.run.app')}"}
    assert (await _post(app, bad)).status_code == 401
    assert repo.get_session("u1", "old").state == "transcribing"


async def test_endpoint_fails_stale_leaves_fresh_and_is_idempotent(app, repo):
    mk(repo, "old", "transcribing", LIMIT["transcribing"] + 1)
    mk(repo, "fresh", "transcribing", 60, uid="u2")
    mk(repo, "done", "awaiting_input", 99999, uid="u3")
    h = {"Authorization": f"Bearer {mint()}"}
    r = await _post(app, h)
    assert r.status_code == 200 and r.json() == {"transcribing": 1, "validating": 0}
    assert repo.get_session("u1", "old").state == "failed"
    assert repo.get_session("u2", "fresh").state == "transcribing"
    assert repo.get_session("u3", "done").state == "awaiting_input"
    assert (await _post(app, h)).json() == {"transcribing": 0, "validating": 0}


async def test_endpoint_is_hidden_from_the_schema_and_kind_route_still_works(app):
    assert not any(p.startswith("/tasks") for p in app.openapi()["paths"])
    h = {"Authorization": f"Bearer {mint()}"}
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app, raise_app_exceptions=False), base_url="http://t"
    ) as c:
        r = await c.post("/tasks/nope", json={"kind": "validate", "uid": "u", "sid": "s"}, headers=h)
    assert r.status_code == 404
