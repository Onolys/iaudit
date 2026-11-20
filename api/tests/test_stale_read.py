"""Lazy stale check: a session left in `transcribing` past its cap (+60 s) is failed when it is
read (GET /v1/sessions/{id}, the list), because the web app only reads the API on demand and
there is no cron. Fake clock via `app.state.clock`."""

from datetime import UTC, datetime, timedelta

import pytest

from onolys_api.app import create_app
from onolys_api.jobs.stale import STALE_MARGIN_S
from onolys_api.repo.fake import FakeRepo
from onolys_api.repo.models import SessionDoc, SessionStatusDoc, StepRecord

pytestmark = pytest.mark.unit
A = {"Authorization": "Bearer test:alice"}
T0 = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)


class Clock:
    def __init__(self) -> None:
        self.now = T0

    def __call__(self) -> datetime:
        return self.now


@pytest.fixture
def repo(blobs):
    return FakeRepo(blobs)


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def app(settings, blobs, repo, clock):
    a = create_app(settings, repo=repo, blobs=blobs)
    a.state.clock = clock
    return a


def seed(repo, sid="s1", state="transcribing", limit=600.0, at=T0, op="op-1"):
    steps = {"transcribe": StepRecord(status="pending", stt_operation=op, stt_started=at,
                                      stt_limit_s=limit)}  # fmt: skip
    repo.create_session(
        "alice", sid,
        SessionDoc(uid="alice", state=state, step="transcribe", steps=steps,
                   created_at=at, updated_at=at),
        SessionStatusDoc(uid="alice", state=state, step="transcribe", progress=20, updated_at=at),
    )  # fmt: skip


async def get(client, sid="s1"):
    return await client.get(f"/v1/sessions/{sid}", headers=A)


async def test_read_inside_the_cap_leaves_it_alone(client, repo, clock):
    seed(repo, limit=600)
    clock.now = T0 + timedelta(seconds=600 + STALE_MARGIN_S - 1)
    body = (await get(client)).json()
    assert body["status"] == "transcribing" and body["error"] is None


async def test_read_past_cap_plus_margin_fails_it(client, repo, clock):
    seed(repo, limit=600)
    clock.now = T0 + timedelta(seconds=600 + STALE_MARGIN_S + 1)
    body = (await get(client)).json()
    assert body["status"] == "failed"
    assert body["error"] == {"code": "transcription_failed"}
    s, st = repo.get_session("alice", "s1"), repo.get_status("alice", "s1")
    assert (s.state, s.steps["transcribe"].status) == ("failed", "failed")
    assert (st.state, st.error_code) == ("failed", "transcription_failed")  # the web listener


async def test_second_read_is_idempotent(client, repo, clock):
    seed(repo, limit=600)
    clock.now = T0 + timedelta(seconds=700)
    await get(client)
    writes = len(repo.status_writes)
    body = (await get(client)).json()
    assert body["status"] == "failed" and len(repo.status_writes) == writes


async def test_cap_comes_from_the_stored_limit(client, repo, clock):
    seed(repo, limit=300)  # a short recording
    clock.now = T0 + timedelta(seconds=300 + STALE_MARGIN_S + 1)
    assert (await get(client)).json()["status"] == "failed"


async def test_no_stored_limit_uses_the_settings_maximum(client, repo, clock):
    seed(repo, limit=None)
    clock.now = T0 + timedelta(seconds=1200 + STALE_MARGIN_S - 1)
    assert (await get(client)).json()["status"] == "transcribing"
    clock.now = T0 + timedelta(seconds=1200 + STALE_MARGIN_S + 1)
    assert (await get(client)).json()["status"] == "failed"


async def test_other_states_are_never_touched(client, repo, clock):
    seed(repo, "a", state="awaiting_input")
    seed(repo, "b", state="running")
    clock.now = T0 + timedelta(hours=5)
    assert (await get(client, "a")).json()["status"] == "awaiting_input"
    assert (await get(client, "b")).json()["status"] == "running"


async def test_a_poll_that_just_finished_wins_the_race(client, repo, clock, monkeypatch):
    """The read decides from an old snapshot; the transaction sees the session moved on."""
    seed(repo, limit=600)
    clock.now = T0 + timedelta(seconds=900)
    real = repo.fail_stale_session

    def racing(uid, sid, state, before, error):
        repo.update_session(uid, sid, {"state": "awaiting_input"},
                            status={"state": "awaiting_input"})  # fmt: skip
        return real(uid, sid, state, before, error)

    monkeypatch.setattr(repo, "fail_stale_session", racing)
    body = (await get(client)).json()
    assert body["status"] == "awaiting_input" and body["error"] is None


async def test_chain_that_never_started_is_failed_too(client, repo, clock):
    """validate moved it to transcribing, the transcribe task was dropped: no stt_started."""
    repo.create_session(
        "alice", "s1",
        SessionDoc(uid="alice", state="transcribing", step="transcribe", created_at=T0,
                   updated_at=T0),
        SessionStatusDoc(uid="alice", state="transcribing", step="transcribe", updated_at=T0),
    )  # fmt: skip
    clock.now = T0 + timedelta(seconds=1200 + STALE_MARGIN_S + 1)
    body = (await get(client)).json()
    assert body["status"] == "failed" and body["error"] == {"code": "transcription_failed"}


async def test_list_fails_stale_items_too(client, repo, clock):
    seed(repo, "old", limit=600)
    seed(repo, "new", limit=600, at=T0 + timedelta(seconds=800))
    clock.now = T0 + timedelta(seconds=900)
    items = {i["id"]: i for i in (await client.get("/v1/sessions", headers=A)).json()["items"]}
    assert (items["old"]["status"], items["old"]["error_code"]) == (
        "failed",
        "transcription_failed",
    )
    assert items["new"]["status"] == "transcribing"
    assert repo.get_session("alice", "old").state == "failed"
