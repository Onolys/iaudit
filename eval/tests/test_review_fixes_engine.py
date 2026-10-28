"""Review fixes B-1, B-4, B-5, B-6, B-9 at the engine/store level (offline, fake backend)."""

import asyncio
import fcntl
import json
import os
import shutil
import threading

import pytest
from fakes.fake_backend import FakeBackend

from iaudit_eval import paths, store
from iaudit_eval.client import AuditClient
from iaudit_eval.datasets import load
from iaudit_eval.engine import Selection, resume, start_run

URL = "http://fake"


async def _nosleep(_s):
    return None


def _client(fb):
    return AuditClient(URL, transport=fb.transport(), sleep=_nosleep)


@pytest.fixture(scope="module")
def synth():
    return load("synthetic")


async def test_drain_lets_inflight_finish_and_stores_no_terminal_state(synth, tmp_path):
    fb = FakeBackend("ok", delay=0.05)
    h = start_run(synth, Selection(split="all"), base_url=URL, runs_root=tmp_path,
                  client=_client(fb), concurrency=2, on_finish=None)  # fmt: skip
    await asyncio.sleep(0.07)  # canary done, two items in flight
    h.drain()
    await h.wait()
    stored = list(store.iter_items(tmp_path, h.run_id))
    assert stored and len(stored) == fb.count < 8  # every request that was sent was written
    assert store.load_run(tmp_path, h.run_id)["state"] == "running"
    assert store.effective_state(tmp_path, h.run_id) == "interrupted"
    # resumable: finishes the rest
    r = resume(h.run_id, client=_client(FakeBackend("ok")), runs_root=tmp_path, on_finish=None)
    assert await r.wait() == "finished"


async def test_cap_reached_by_last_item_is_finished_not_aborted_cost(synth, tmp_path):
    fb = FakeBackend("ok", cost_usd=0.01)
    h = start_run(synth, Selection(split="all"), base_url=URL, runs_root=tmp_path,
                  client=_client(fb), concurrency=1, max_cost_usd=0.08, on_finish=None)  # fmt: skip
    assert await h.wait() == "finished"
    assert fb.count == 8
    assert store.load_run(tmp_path, h.run_id)["state"] == "finished"


async def test_resume_cap_keep_clear_and_replace(synth, tmp_path):
    fb = FakeBackend("missing_cost")
    h = start_run(synth, Selection(split="all"), base_url=URL, runs_root=tmp_path,
                  client=_client(fb), max_cost_usd=5.0, on_finish=None)  # fmt: skip
    await h.wait()
    assert h.state == "failed"
    # keep (default): the stored cap still cannot be enforced
    r = resume(h.run_id, client=_client(fb), runs_root=tmp_path, on_finish=None)
    await r.wait()
    assert r.state == "failed"
    assert store.load_run(tmp_path, h.run_id)["max_cost_usd"] == 5.0
    # replace
    r = resume(h.run_id, max_cost_usd=7.0, client=_client(fb), runs_root=tmp_path, on_finish=None)
    await r.wait()
    assert store.load_run(tmp_path, h.run_id)["max_cost_usd"] == 7.0
    # clear: no cap, no cost handling
    r = resume(h.run_id, max_cost_usd=None, client=_client(fb), runs_root=tmp_path,
               on_finish=None)  # fmt: skip
    assert await r.wait() == "finished"
    assert store.load_run(tmp_path, h.run_id)["max_cost_usd"] is None


def _hold_shared_briefly(path, held, seconds):
    fd = os.open(path, os.O_RDONLY)
    fcntl.flock(fd, fcntl.LOCK_SH)
    held.set()
    threading.Event().wait(seconds)
    os.close(fd)


def test_is_locked_probe_does_not_make_writer_fail(tmp_path):
    run_id = "20261021T000000Z-synthetic-aaaaaa"
    lock = store.RunLock(tmp_path, run_id)
    lock.path.parent.mkdir(parents=True)
    lock.path.touch()
    held = threading.Event()
    t = threading.Thread(target=_hold_shared_briefly, args=(lock.path, held, 0.05))
    t.start()
    held.wait()
    try:
        lock.acquire()  # a concurrent shared probe must not surface as RunLockedError
    finally:
        lock.release()
        t.join()


def test_is_locked_true_only_while_writer_holds_it(tmp_path):
    run_id = "20261021T000000Z-synthetic-bbbbbb"
    assert store.is_locked(tmp_path, run_id) is False
    with store.RunLock(tmp_path, run_id):
        assert store.is_locked(tmp_path, run_id) is True
        with pytest.raises(store.RunLockedError):
            store.RunLock(tmp_path, run_id).acquire()
    assert store.is_locked(tmp_path, run_id) is False


async def test_lock_failure_on_start_leaves_no_run_dir(synth, tmp_path, monkeypatch):
    def locked(self):
        raise store.RunLockedError("locked")

    monkeypatch.setattr(store.RunLock, "acquire", locked)
    with pytest.raises(store.RunLockedError):
        start_run(synth, Selection(split="all"), base_url=URL, runs_root=tmp_path,
                  client=_client(FakeBackend("ok")))  # fmt: skip
    assert list(tmp_path.iterdir()) == []


async def test_auto_score_uses_the_runs_datasets_root(tmp_path):
    root = tmp_path / "datasets"
    shutil.copytree(paths.datasets_dir() / "eaudit/synthetic", root / "eaudit/synth2")
    meta = json.loads((root / "eaudit/synth2" / "metadata.json").read_text())
    meta["name"] = "synth2"
    (root / "eaudit/synth2" / "metadata.json").write_text(json.dumps(meta))
    runs = tmp_path / "runs"
    h = start_run("synth2", Selection(split="all"), base_url=URL, runs_root=runs,
                  datasets_root=root, client=_client(FakeBackend("ok")))  # fmt: skip
    await h.wait()
    assert (runs / h.run_id / "metrics.json").is_file()
