"""Speakers, transcript read and the first-run gate (R2, R4, D13, AC13, AC18).

Runs on FakeRepo always and on the Firestore emulator when FIRESTORE_EMULATOR_HOST is set.
"""

import itertools
import os
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime

import httpx
import pytest
from onolys_core.transcript import Transcript, Turn
from starlette.testclient import TestClient

from onolys_api.app import create_app
from onolys_api.config import Settings
from onolys_api.jobs import caps
from onolys_api.jobs.first_run import maybe_start_first_run
from onolys_api.jobs.machine import advance
from onolys_api.jobs.queue import TaskPayload
from onolys_api.repo.fake import FakeRepo
from onolys_api.repo.models import RatingDoc, ReportDoc, SttInfo

pytestmark = pytest.mark.unit
HAS_EMULATOR = bool(os.environ.get("FIRESTORE_EMULATOR_HOST"))
TID = "current"
CARD = {"change_goal": "g", "notes": "n"}


@pytest.fixture(params=["fake", "firestore"])
def repo(request, tmp_path):
    from onolys_api.storage.fake import FakeBlobStore

    blobs = FakeBlobStore(tmp_path / "blobs", bucket="test-bucket")
    if request.param == "fake":
        return FakeRepo(blobs)
    if not HAS_EMULATOR:
        pytest.skip("FIRESTORE_EMULATOR_HOST not set")
    from google.auth.credentials import AnonymousCredentials
    from google.cloud import firestore

    from onolys_api.repo.firestore import FirestoreRepo

    return FirestoreRepo(
        firestore.Client(project="demo-onolys", credentials=AnonymousCredentials()), blobs
    )


class RecordingQueue:
    def __init__(self, fail: bool = False) -> None:
        self.calls: list[TaskPayload] = []
        self.fail = fail
        self._lock = threading.Lock()

    def enqueue(self, payload: TaskPayload, delay_s: float = 0.0) -> None:
        if self.fail:
            raise RuntimeError("queue down")
        with self._lock:
            self.calls.append(payload)

    @property
    def runs(self) -> list[TaskPayload]:
        return [c for c in self.calls if c.kind == "run"]


def mk_settings(**kw) -> Settings:
    return Settings(env="test", auth_mode="fake", git_sha="sha-test", **kw)


def transcript(speakers=("S1", "S2"), turns_each=4) -> Transcript:
    turns = []
    for _ in range(turns_each):
        for sp in speakers:
            turns.append(
                Turn(id=f"t{len(turns)}", speaker=sp, text=f"line {len(turns)} by {sp}",
                     start_ms=len(turns) * 1000, end_ms=len(turns) * 1000 + 900)
            )  # fmt: skip
    return Transcript(turns=turns, language="en", duration_ms=len(turns) * 1000)


def new_session(repo, uid, *, state="transcribing", ready=False, speakers=("S1", "S2"), **fields):
    """A session created through the app's own repo calls, put into `state`."""
    from onolys_api.repo.models import SessionDoc, SessionStatusDoc

    sid = uuid.uuid4().hex
    now = datetime.now(UTC)
    repo.create_session(
        uid, sid,
        SessionDoc(uid=uid, n_runs=2, preset="p1", stt=SttInfo(provider="x", model="m", language="en"),
                   created_at=now, updated_at=now),
        SessionStatusDoc(uid=uid, updated_at=now),
    )  # fmt: skip
    repo.put_transcript(uid, sid, TID, transcript(speakers))
    flags = {"transcript_ready": True} if ready else {}
    repo.update_session(
        uid, sid, {"state": state, **flags, **fields}, status={"state": state, **flags}
    )
    return sid


def rate(repo, uid, sid) -> str:
    rid = uuid.uuid4().hex
    repo.put_rating_revision(
        uid, sid, rid, RatingDoc(card={"change_goal": "g"}, created_at=datetime.now(UTC))
    )
    return rid


def set_flags(repo, uid, sid, **flags):
    repo.update_session(uid, sid, dict(flags), status=dict(flags))


def user_counters(repo, uid, date):
    u = repo.get_user(uid)
    return (u.active_runs if u else 0), repo.get_usage(uid, date).runs


def make_client(repo, settings=None, queue=None):
    app = create_app(settings or mk_settings(), repo=repo, blobs=repo._blobs)
    app.state.queue = queue if queue is not None else RecordingQueue()
    return app


@pytest.fixture
async def env(repo):
    queue = RecordingQueue()
    app = make_client(repo, queue=queue)
    uid = f"u{uuid.uuid4().hex[:10]}"
    h = {"Authorization": f"Bearer test:{uid}"}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        yield c, h, repo, uid, queue


# ---------------------------------------------------------------- the gate (repo level)


def test_starts_run_when_all_three_inputs_present(repo):
    uid, queue, s = "u1" + uuid.uuid4().hex[:6], RecordingQueue(), mk_settings()
    sid = new_session(repo, uid, state="awaiting_input", ready=True, clinician_speaker="S1")
    rid = rate(repo, uid, sid)
    set_flags(repo, uid, sid, speaker_confirmed=True, rating_submitted=True)
    maybe_start_first_run(repo, queue, uid, sid, s)
    sess = repo.get_session(uid, sid)
    assert sess.state == "running" and sess.first_run_id
    st = repo.get_status(uid, sid)
    assert st.state == "running" and st.progress == 45 and st.error_code is None
    (run,) = repo.list_runs(uid, sid)
    assert run.run_id == sess.first_run_id and run.status == "pending"
    assert (run.rating_id, run.n_runs, run.preset, run.code_version) == (rid, 2, "p1", "sha-test")
    assert run.stt == SttInfo(provider="x", model="m", language="en")
    assert [(c.kind, c.run_id, c.uid, c.sid) for c in queue.calls] == [
        ("run", run.run_id, uid, sid)
    ]
    assert user_counters(repo, uid, caps.utc_date()) == (1, 1)


@pytest.mark.parametrize("missing", ["transcript_ready", "speaker_confirmed", "rating_submitted"])
def test_nothing_starts_while_an_input_is_missing(repo, missing):
    uid, queue = "u2" + uuid.uuid4().hex[:6], RecordingQueue()
    sid = new_session(repo, uid, state="awaiting_input", ready=True)
    rate(repo, uid, sid)
    flags = {"transcript_ready": True, "speaker_confirmed": True, "rating_submitted": True}
    flags[missing] = False
    set_flags(repo, uid, sid, **flags)
    maybe_start_first_run(repo, queue, uid, sid, mk_settings())
    assert repo.get_session(uid, sid).state == "awaiting_input"
    assert repo.list_runs(uid, sid) == [] and queue.calls == []
    assert user_counters(repo, uid, caps.utc_date()) == (0, 0)


def test_no_rating_revision_still_starts_with_null_rating_id(repo):
    uid, queue = "u3" + uuid.uuid4().hex[:6], RecordingQueue()
    sid = new_session(repo, uid, state="awaiting_input", ready=True)
    set_flags(repo, uid, sid, speaker_confirmed=True, rating_submitted=True)
    maybe_start_first_run(repo, queue, uid, sid, mk_settings())
    (run,) = repo.list_runs(uid, sid)
    assert run.rating_id is None


def test_second_call_is_a_noop(repo):
    uid, queue = "u4" + uuid.uuid4().hex[:6], RecordingQueue()
    sid = new_session(repo, uid, state="awaiting_input", ready=True)
    set_flags(repo, uid, sid, speaker_confirmed=True, rating_submitted=True)
    for _ in range(3):
        maybe_start_first_run(repo, queue, uid, sid, mk_settings())
    assert len(repo.list_runs(uid, sid)) == 1 and len(queue.runs) == 1
    assert user_counters(repo, uid, caps.utc_date()) == (1, 1)


@pytest.mark.parametrize("kw", [{"daily_run_cap": 0}, {"max_active_runs": 0}])
def test_cap_hit_leaves_awaiting_input_with_error_code_and_leaks_nothing(repo, kw):
    uid, queue = "u5" + uuid.uuid4().hex[:6], RecordingQueue()
    sid = new_session(repo, uid, state="awaiting_input", ready=True)
    set_flags(repo, uid, sid, speaker_confirmed=True, rating_submitted=True)
    maybe_start_first_run(repo, queue, uid, sid, mk_settings(**kw))
    sess = repo.get_session(uid, sid)
    assert sess.state == "awaiting_input" and sess.first_run_id is None
    assert sess.error is not None and sess.error.code == "daily_cap_reached"
    assert repo.get_status(uid, sid).error_code == "daily_cap_reached"
    assert repo.list_runs(uid, sid) == [] and queue.calls == []
    assert user_counters(repo, uid, caps.utc_date()) == (0, 0)
    # the cap clears: the next trigger starts the run and clears the code
    maybe_start_first_run(repo, queue, uid, sid, mk_settings())
    sess = repo.get_session(uid, sid)
    assert sess.state == "running" and sess.error is None
    assert repo.get_status(uid, sid).error_code is None and len(queue.runs) == 1


def test_cap_race_two_sessions_same_user_exactly_one_starts_no_leak(repo):
    uid, queue = "u6" + uuid.uuid4().hex[:6], RecordingQueue()
    s = mk_settings(daily_run_cap=1)
    sids = []
    for _ in range(2):
        sid = new_session(repo, uid, state="awaiting_input", ready=True)
        set_flags(repo, uid, sid, speaker_confirmed=True, rating_submitted=True)
        sids.append(sid)
    barrier = threading.Barrier(2)

    def go(sid):
        barrier.wait()
        maybe_start_first_run(repo, queue, uid, sid, s)

    with ThreadPoolExecutor(2) as ex:
        list(ex.map(go, sids))
    states = sorted(repo.get_session(uid, sid).state for sid in sids)
    assert states == ["awaiting_input", "running"] and len(queue.runs) == 1
    assert user_counters(repo, uid, caps.utc_date()) == (1, 1)


def test_enqueue_failure_after_commit_fails_the_run_and_refunds(repo):
    uid = "u7" + uuid.uuid4().hex[:6]
    sid = new_session(repo, uid, state="awaiting_input", ready=True)
    set_flags(repo, uid, sid, speaker_confirmed=True, rating_submitted=True)
    maybe_start_first_run(repo, RecordingQueue(fail=True), uid, sid, mk_settings())
    sess = repo.get_session(uid, sid)
    assert sess.state == "failed" and sess.error is not None
    assert sess.error.code == "upstream_unavailable"
    (run,) = repo.list_runs(uid, sid)
    assert run.status == "failed"
    assert user_counters(repo, uid, caps.utc_date()) == (0, 0)


def test_no_queue_does_not_start(repo):
    uid = "u8" + uuid.uuid4().hex[:6]
    sid = new_session(repo, uid, state="awaiting_input", ready=True)
    set_flags(repo, uid, sid, speaker_confirmed=True, rating_submitted=True)
    maybe_start_first_run(repo, None, uid, sid, mk_settings())
    assert repo.get_session(uid, sid).state == "awaiting_input" and repo.list_runs(uid, sid) == []


# ---------------------------------------------------------------- AC13: the race

INPUTS = ("transcript", "speaker", "rating")
ORDERS = list(itertools.permutations(INPUTS))


def _land(repo, queue, settings, uid, sid, which):
    """One input landing, exactly as its caller does it: set its flag, then call the hook."""
    if which == "transcript":
        advance(repo, uid, sid, to="awaiting_input", step=None, flags={"transcript_ready": True})
    elif which == "speaker":
        set_flags(repo, uid, sid, speaker_confirmed=True, clinician_speaker="S1")
    else:
        rate(repo, uid, sid)
        set_flags(repo, uid, sid, rating_submitted=True)
    maybe_start_first_run(repo, queue, uid, sid, settings)


def _assert_one_run(repo, queue, uid, sid):
    sess = repo.get_session(uid, sid)
    runs = repo.list_runs(uid, sid)
    assert len(runs) == 1 and len(queue.runs) == 1
    assert sess.first_run_id == runs[0].run_id == queue.runs[0].run_id
    assert sess.state == "running"
    assert user_counters(repo, uid, caps.utc_date()) == (1, 1)


@pytest.mark.parametrize("order", ORDERS, ids=["-".join(o) for o in ORDERS])
def test_race_all_orders_sequential_and_concurrent(repo, order):
    s = mk_settings()
    for rnd in range(4):
        uid, queue = f"r{rnd}" + uuid.uuid4().hex[:6], RecordingQueue()
        sid = new_session(repo, uid)
        for which in order:  # sequential in this order
            _land(repo, queue, s, uid, sid, which)
        _assert_one_run(repo, queue, uid, sid)

        uid, queue = f"c{rnd}" + uuid.uuid4().hex[:6], RecordingQueue()
        sid = new_session(repo, uid)
        barrier = threading.Barrier(3)

        def go(which, uid=uid, queue=queue, sid=sid, barrier=barrier):
            barrier.wait()
            _land(repo, queue, s, uid, sid, which)

        with ThreadPoolExecutor(3) as ex:  # submitted in `order`, interleaved by the scheduler
            for f in [ex.submit(go, w) for w in order]:
                f.result()
        _assert_one_run(repo, queue, uid, sid)


def test_race_over_http_all_orders_repeated(repo):
    """PUT rating final, speakers/confirm and transcribe completion, concurrently. A confirm that
    arrives before the transcript is ready gets 409 and is retried, as a client would."""
    s = mk_settings()
    for order in ORDERS:
        for _ in range(2):
            queue = RecordingQueue()
            app = make_client(repo, s, queue)
            uid = f"h{uuid.uuid4().hex[:8]}"
            h = {"Authorization": f"Bearer test:{uid}"}
            sid = new_session(repo, uid)
            barrier = threading.Barrier(3)

            def act(which, app=app, h=h, uid=uid, sid=sid, queue=queue, barrier=barrier):
                barrier.wait()
                if which == "transcript":
                    advance(repo, uid, sid, to="awaiting_input", step=None,
                            flags={"transcript_ready": True})  # fmt: skip
                    maybe_start_first_run(repo, queue, uid, sid, s)
                    return
                with TestClient(app) as c:
                    for _ in range(200):
                        if which == "rating":
                            r = c.put(f"/v1/sessions/{sid}/rating", headers=h,
                                      json={"final": True, "card": CARD})  # fmt: skip
                        else:
                            r = c.post(f"/v1/sessions/{sid}/speakers/confirm", headers=h,
                                       json={"clinician_speaker": "S1"})  # fmt: skip
                        if r.status_code != 409:
                            break
                    assert r.status_code == 202, r.text

            with ThreadPoolExecutor(3) as ex:
                for f in [ex.submit(act, w) for w in order]:
                    f.result()
            _assert_one_run(repo, queue, uid, sid)


# ---------------------------------------------------------------- speakers + transcript (HTTP)


async def test_speakers_lists_three_samples_each_and_all_speakers(env):
    c, h, repo, uid, _ = env
    sid = new_session(repo, uid, state="awaiting_input", ready=True, speakers=("A", "B", "C"))
    r = await c.get(f"/v1/sessions/{sid}/speakers", headers=h)
    assert r.status_code == 200
    j = r.json()
    assert [s["speaker"] for s in j["speakers"]] == ["A", "B", "C"]
    for s in j["speakers"]:
        assert len(s["samples"]) == 3 and all(s["speaker"] in t for t in s["samples"])
        assert s["turn_count"] == 4
    assert j["clinician_speaker"] is None


async def test_speakers_409_before_transcript_ready_and_404_foreign(env):
    c, h, repo, uid, _ = env
    sid = new_session(repo, uid, state="transcribing")
    r = await c.get(f"/v1/sessions/{sid}/speakers", headers=h)
    assert r.status_code == 409 and r.json()["details"][0]["code"] == "invalid_state"
    ok = new_session(repo, uid, state="awaiting_input", ready=True)
    other = {"Authorization": "Bearer test:someone-else"}
    assert (await c.get(f"/v1/sessions/{ok}/speakers", headers=other)).status_code == 404
    body = {"clinician_speaker": "S1"}
    assert (await c.post(f"/v1/sessions/{ok}/speakers/confirm", json=body, headers=other)
            ).status_code == 404  # fmt: skip


async def test_confirm_sets_flag_speaker_and_status(env):
    c, h, repo, uid, queue = env
    sid = new_session(repo, uid, state="awaiting_input", ready=True)
    r = await c.post(f"/v1/sessions/{sid}/speakers/confirm", json={"clinician_speaker": "S2"},
                     headers=h)  # fmt: skip
    assert r.status_code == 202 and r.json()["clinician_speaker"] == "S2"
    s = repo.get_session(uid, sid)
    assert (s.clinician_speaker, s.speaker_confirmed, s.state) == ("S2", True, "awaiting_input")
    assert repo.get_status(uid, sid).speaker_confirmed is True
    assert queue.calls == []  # rating still missing
    g = (await c.get(f"/v1/sessions/{sid}/speakers", headers=h)).json()
    assert g["clinician_speaker"] == "S2"


async def test_confirm_unknown_speaker_422_and_wrong_state_409(env):
    c, h, repo, uid, _ = env
    sid = new_session(repo, uid, state="awaiting_input", ready=True)
    r = await c.post(f"/v1/sessions/{sid}/speakers/confirm", json={"clinician_speaker": "ZZ"},
                     headers=h)  # fmt: skip
    assert r.status_code == 422 and r.json()["details"][0]["code"] == "invalid_parameters"
    assert repo.get_session(uid, sid).speaker_confirmed is False
    for state, ready in (("transcribing", False), ("running", True)):
        sid = new_session(repo, uid, state=state, ready=ready)
        r = await c.post(f"/v1/sessions/{sid}/speakers/confirm", json={"clinician_speaker": "S1"},
                         headers=h)  # fmt: skip
        assert r.status_code == 409 and r.json()["details"][0]["code"] == "invalid_state"


async def test_confirm_in_report_ready_changes_next_run_only_report_unchanged(env):
    """AC18."""
    c, h, repo, uid, queue = env
    sid = new_session(repo, uid, state="report_ready", ready=True, clinician_speaker="S1",
                      speaker_confirmed=True, rating_submitted=True, first_run_id="run0",
                      latest_report_version=1)  # fmt: skip
    repo.put_report(uid, sid, "rep1", ReportDoc(version=1, run_id="run0", report={"k": "v"}))
    before = repo.get_report(uid, sid, "rep1")
    r = await c.post(f"/v1/sessions/{sid}/speakers/confirm", json={"clinician_speaker": "S2"},
                     headers=h)  # fmt: skip
    assert r.status_code == 202
    s = repo.get_session(uid, sid)
    assert (s.clinician_speaker, s.state, s.first_run_id) == ("S2", "report_ready", "run0")
    assert repo.get_report(uid, sid, "rep1") == before
    assert repo.list_reports(uid, sid) == [before]
    assert repo.list_runs(uid, sid) == [] and queue.calls == []
    assert repo.get_status(uid, sid).state == "report_ready"


async def test_confirm_in_failed_allowed(env):
    c, h, repo, uid, queue = env
    sid = new_session(repo, uid, state="failed", ready=True, clinician_speaker="S1",
                      speaker_confirmed=True, first_run_id="run0")  # fmt: skip
    r = await c.post(f"/v1/sessions/{sid}/speakers/confirm", json={"clinician_speaker": "S2"},
                     headers=h)  # fmt: skip
    assert r.status_code == 202 and repo.get_session(uid, sid).clinician_speaker == "S2"
    assert queue.calls == []


async def test_transcript_read_owner_scoped_no_store_with_roles(env):
    c, h, repo, uid, _ = env
    sid = new_session(repo, uid, state="awaiting_input", ready=True)
    r = await c.get(f"/v1/sessions/{sid}/transcript", headers=h)
    assert r.status_code == 200 and r.headers["cache-control"] == "private, no-store"
    j = r.json()
    assert j["language"] == "en" and j["duration_ms"] == 8000 and j["clinician_speaker"] is None
    assert len(j["turns"]) == 8 and all(t["role"] is None for t in j["turns"])
    assert set(j["turns"][0]) == {"id", "speaker", "role", "start_ms", "end_ms", "text"}
    await c.post(f"/v1/sessions/{sid}/speakers/confirm", json={"clinician_speaker": "S2"},
                 headers=h)  # fmt: skip
    j = (await c.get(f"/v1/sessions/{sid}/transcript", headers=h)).json()
    assert j["clinician_speaker"] == "S2"
    assert {(t["speaker"], t["role"]) for t in j["turns"]} == {
        ("S1", "client"),
        ("S2", "clinician"),
    }
    other = {"Authorization": "Bearer test:someone-else"}
    assert (await c.get(f"/v1/sessions/{sid}/transcript", headers=other)).status_code == 404


async def test_transcript_409_before_ready(env):
    c, h, repo, uid, _ = env
    sid = new_session(repo, uid, state="transcribing")
    r = await c.get(f"/v1/sessions/{sid}/transcript", headers=h)
    assert r.status_code == 409 and r.json()["details"][0]["code"] == "invalid_state"


async def test_confirm_then_rating_over_http_starts_exactly_one_run(env):
    c, h, repo, uid, queue = env
    sid = new_session(repo, uid, state="awaiting_input", ready=True)
    await c.post(f"/v1/sessions/{sid}/speakers/confirm", json={"clinician_speaker": "S1"},
                 headers=h)  # fmt: skip
    assert queue.calls == []
    r = await c.put(f"/v1/sessions/{sid}/rating", headers=h,
                    json={"final": True, "card": {"change_goal": "g", "notes": "n"}})  # fmt: skip
    assert r.status_code == 202
    _assert_one_run(repo, queue, uid, sid)
    assert (await c.get(f"/v1/sessions/{sid}", headers=h)).json()["status"] == "running"
