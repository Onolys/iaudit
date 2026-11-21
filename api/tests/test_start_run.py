"""`POST /runs` starts a run atomically: the state check, the cap reservation, the run creation,
`first_run_id` and the move to `running` are one repo transaction (`Repo.start_run`), so two
concurrent starts, or a manual start against the auto first run, cannot both win.

Runs on FakeRepo always and on the Firestore emulator when FIRESTORE_EMULATOR_HOST is set.
"""

import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor

import pytest
from starlette.testclient import TestClient
from test_first_run import (
    RecordingQueue,
    make_client,
    mk_settings,
    new_session,
    rate,
    repo,  # noqa: F401  (fixture)
    set_flags,
    user_counters,
)

from onolys_api.jobs import caps
from onolys_api.jobs.first_run import maybe_start_first_run
from onolys_api.repo.fake import FakeRepo

pytestmark = pytest.mark.unit
READY = {"transcript_ready": True, "speaker_confirmed": True, "clinician_speaker": "S1"}


class SlowReadRepo(FakeRepo):
    """Widens the read-then-write window so a non-atomic start reliably interleaves."""

    def get_session(self, uid, sid):
        s = super().get_session(uid, sid)
        time.sleep(0.05)
        return s


def _widen(r):
    if isinstance(r, FakeRepo):
        r.__class__ = SlowReadRepo


def _post(app, h, sid, barrier):
    with TestClient(app) as c:
        barrier.wait()
        return c.post(f"/v1/sessions/{sid}/runs", json={}, headers=h)


@pytest.mark.parametrize("state", ["report_ready", "failed"])
def test_two_concurrent_manual_starts_exactly_one_wins(repo, state):  # noqa: F811
    _widen(repo)
    queue = RecordingQueue()
    app = make_client(repo, mk_settings(max_active_runs=2), queue)
    uid = f"u{uuid.uuid4().hex[:10]}"
    h = {"Authorization": f"Bearer test:{uid}"}
    sid = new_session(repo, uid, state=state, ready=True, **READY)
    barrier = threading.Barrier(2)
    with ThreadPoolExecutor(2) as ex:
        rs = [f.result() for f in [ex.submit(_post, app, h, sid, barrier) for _ in range(2)]]
    assert sorted(r.status_code for r in rs) == [202, 409], [r.text for r in rs]
    loser = next(r for r in rs if r.status_code == 409)
    assert loser.json()["details"][0]["code"] == "invalid_state"
    assert len(repo.list_runs(uid, sid)) == 1
    assert len(queue.runs) == 1
    assert repo.get_session(uid, sid).state == "running"
    assert user_counters(repo, uid, caps.utc_date()) == (1, 1)  # the loser holds no slot


def test_manual_start_vs_auto_first_run_exactly_one_run(repo):  # noqa: F811
    _widen(repo)
    s = mk_settings(max_active_runs=2)
    for _ in range(3):
        queue = RecordingQueue()
        app = make_client(repo, s, queue)
        uid = f"u{uuid.uuid4().hex[:10]}"
        h = {"Authorization": f"Bearer test:{uid}"}
        sid = new_session(repo, uid, state="awaiting_input", ready=True, **READY)
        set_flags(repo, uid, sid, rating_submitted=True)
        rate(repo, uid, sid)
        barrier = threading.Barrier(2)

        def auto(sid=sid, uid=uid, queue=queue, barrier=barrier):
            barrier.wait()
            maybe_start_first_run(repo, queue, uid, sid, s)

        with ThreadPoolExecutor(2) as ex:
            fa = ex.submit(auto)
            fm = ex.submit(_post, app, h, sid, barrier)
            fa.result()
            r = fm.result()
        assert r.status_code in (202, 409)
        assert len(repo.list_runs(uid, sid)) == 1
        assert len(queue.runs) == 1
        sess = repo.get_session(uid, sid)
        assert sess.first_run_id == repo.list_runs(uid, sid)[0].run_id
        assert user_counters(repo, uid, caps.utc_date()) == (1, 1)


def test_manual_start_sets_first_run_id_when_unset(repo):  # noqa: F811
    queue = RecordingQueue()
    app = make_client(repo, mk_settings(), queue)
    uid = f"u{uuid.uuid4().hex[:10]}"
    h = {"Authorization": f"Bearer test:{uid}"}
    sid = new_session(repo, uid, state="awaiting_input", ready=True, **READY)
    with TestClient(app) as c:
        r = c.post(f"/v1/sessions/{sid}/runs", json={}, headers=h)
    assert r.status_code == 202
    assert repo.get_session(uid, sid).first_run_id == r.json()["run_id"]
    # the first-run gate now finds it taken
    set_flags(repo, uid, sid, rating_submitted=True)
    maybe_start_first_run(repo, queue, uid, sid, mk_settings())
    assert len(repo.list_runs(uid, sid)) == 1


def test_refused_start_reserves_nothing(repo):  # noqa: F811
    queue = RecordingQueue()
    app = make_client(repo, mk_settings(max_active_runs=2, daily_run_cap=0), queue)
    uid = f"u{uuid.uuid4().hex[:10]}"
    h = {"Authorization": f"Bearer test:{uid}"}
    sid = new_session(repo, uid, state="report_ready", ready=True, **READY)
    with TestClient(app) as c:
        r = c.post(f"/v1/sessions/{sid}/runs", json={}, headers=h)
    assert r.status_code == 429 and r.json()["details"][0]["code"] == "daily_cap_reached"
    assert repo.get_session(uid, sid).state == "report_ready"
    assert repo.list_runs(uid, sid) == []
    assert user_counters(repo, uid, caps.utc_date()) == (0, 0)
