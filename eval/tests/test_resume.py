import asyncio
import dataclasses
import json

import pytest
from fakes.fake_backend import FakeBackend

from iaudit_eval import engine, store
from iaudit_eval.client import AuditClient
from iaudit_eval.datasets import load
from iaudit_eval.engine import (
    FingerprintChanged,
    ResumeError,
    SchemaVersionChanged,
    Selection,
    resume,
    start_run,
)

URL = "http://fake"


@pytest.fixture(scope="module")
def synth():
    return load("synthetic")


async def _nosleep(_s):
    return None


def _client(fb):
    return AuditClient(URL, transport=fb.transport(), sleep=_nosleep)


async def _first(ds, fb, tmp_path, **kw):
    h = start_run(ds, Selection(split="all"), base_url=URL, runs_root=tmp_path,
                  client=_client(fb), **kw)  # fmt: skip
    await h.wait()
    return h


def _files(tmp_path, run_id):
    d = store.run_dir(tmp_path, run_id)
    return {str(p.relative_to(d)): p.read_bytes() for p in d.rglob("*.json")}


async def _partial_run(ds, tmp_path):
    """1 ok item, 7 failed (500)."""
    h = await _first(ds, FakeBackend("500", script=["ok"]), tmp_path)
    assert store.load_run(tmp_path, h.run_id)["totals"]["ok"] == 1
    return h


async def test_interrupted_run_resumes_only_missing_and_failed(synth, tmp_path):
    fb = FakeBackend("ok", delay=0.05)
    h = start_run(synth, Selection(split="all"), base_url=URL, runs_root=tmp_path,
                  client=_client(fb), concurrency=2)  # fmt: skip
    await asyncio.sleep(0.12)
    h._task.cancel()
    await asyncio.gather(h._task, return_exceptions=True)
    d = store.run_dir(tmp_path, h.run_id)
    assert not list(d.rglob(".*.tmp"))
    for p in d.rglob("*.json"):
        json.loads(p.read_text())  # no torn files
    assert store.effective_state(tmp_path, h.run_id) == "interrupted"
    done = {i["item_id"] for i in store.iter_items(tmp_path, h.run_id)}
    assert 0 < len(done) < 8
    before = _files(tmp_path, h.run_id)

    fb2 = FakeBackend("ok")
    r = resume(h.run_id, client=_client(fb2), runs_root=tmp_path)
    assert await r.wait() == "finished"
    assert fb2.count == 8 - len(done)
    after = _files(tmp_path, h.run_id)
    for name in before:
        if name.startswith("items/"):
            assert after[name] == before[name]  # ok items never rewritten
    run = store.load_run(tmp_path, h.run_id)
    assert run["totals"]["ok"] == 8 and run["state"] == "finished"
    assert len(run["resumes"]) == 1 and run["mixed"] is False


async def test_resume_retries_failed_items_only(synth, tmp_path):
    h = await _partial_run(synth, tmp_path)
    fb = FakeBackend("ok")
    r = resume(h.run_id, client=_client(fb), runs_root=tmp_path)
    assert await r.wait() == "finished"
    assert fb.count == 7
    assert store.load_run(tmp_path, h.run_id)["totals"]["ok"] == 8
    # nothing left: resume sends nothing
    fb2 = FakeBackend("ok")
    r2 = resume(h.run_id, client=_client(fb2), runs_root=tmp_path)
    assert await r2.wait() == "finished" and fb2.count == 0


@pytest.mark.parametrize("mode", ["changed_models", "changed_prompts"])
async def test_changed_fingerprint_refused_and_resumable(synth, tmp_path, mode):
    h = await _partial_run(synth, tmp_path)
    before = _files(tmp_path, h.run_id)
    fb = FakeBackend(mode)
    r = resume(h.run_id, client=_client(fb), runs_root=tmp_path)
    with pytest.raises(FingerprintChanged) as ei:
        await r.wait()
    assert ei.value.changes
    after = _files(tmp_path, h.run_id)
    assert set(after) == set(before)
    assert after["run.json"] == before["run.json"]  # run.json restored
    ok_items = [n for n in before if n.startswith("items/") and b'"status": "ok"' in before[n]]
    assert ok_items and all(after[n] == before[n] for n in ok_items)
    assert not any(b'"fake-strong-2"' in v for v in after.values())  # refused text not stored
    assert store.effective_state(tmp_path, h.run_id) == "finished"
    # still resumable with the original backend
    r2 = resume(h.run_id, client=_client(FakeBackend("ok")), runs_root=tmp_path)
    assert await r2.wait() == "finished"
    assert store.load_run(tmp_path, h.run_id)["totals"]["ok"] == 8


async def test_refusal_of_interrupted_run_stays_interrupted(synth, tmp_path):
    fb = FakeBackend("ok", delay=0.05)
    h = start_run(synth, Selection(split="all"), base_url=URL, runs_root=tmp_path,
                  client=_client(fb), concurrency=2)  # fmt: skip
    await asyncio.sleep(0.12)
    h._task.cancel()
    await asyncio.gather(h._task, return_exceptions=True)
    r = resume(h.run_id, client=_client(FakeBackend("changed_models")), runs_root=tmp_path)
    with pytest.raises(FingerprintChanged):
        await r.wait()
    assert store.effective_state(tmp_path, h.run_id) == "interrupted"


async def test_allow_mixed_records_change(synth, tmp_path):
    h = await _partial_run(synth, tmp_path)
    orig = store.load_run(tmp_path, h.run_id)["fingerprint"]
    r = resume(h.run_id, allow_mixed=True, client=_client(FakeBackend("changed_models")),
               runs_root=tmp_path)  # fmt: skip
    assert await r.wait() == "finished"
    run = store.load_run(tmp_path, h.run_id)
    assert run["mixed"] is True and run["fingerprint"] == orig
    assert len(run["resumes"]) == 1
    e = run["resumes"][0]
    assert e["allow_mixed"] is True and e["fingerprint"]["models"]["strong"] == "fake-strong-2"
    assert run["warnings"]


async def test_schema_version_change_always_refused(synth, tmp_path):
    h = await _partial_run(synth, tmp_path)
    store.update_run(tmp_path, h.run_id, schema_version="0.0.1")
    r = resume(h.run_id, allow_mixed=True, client=_client(FakeBackend("ok")), runs_root=tmp_path)
    with pytest.raises(SchemaVersionChanged):
        await r.wait()
    assert store.load_run(tmp_path, h.run_id)["schema_version"] == "0.0.1"


async def test_git_change_adds_entry_and_warning_only(synth, tmp_path, monkeypatch):
    h = await _partial_run(synth, tmp_path)
    monkeypatch.setattr(engine, "capture_git", lambda: {
        "git_commit": "f" * 40, "git_dirty": True, "git_diff_sha256": "x"})  # fmt: skip
    r = resume(h.run_id, client=_client(FakeBackend("ok")), runs_root=tmp_path)
    assert await r.wait() == "finished"
    run = store.load_run(tmp_path, h.run_id)
    assert run["mixed"] is False and len(run["resumes"]) == 1
    assert run["resumes"][0]["git_commit"] == "f" * 40
    assert any("git" in w for w in run["warnings"])


async def test_no_fingerprint_yet_first_response_sets_it(synth, tmp_path):
    h = await _first(synth, FakeBackend("500"), tmp_path)
    assert store.load_run(tmp_path, h.run_id)["fingerprint"] is None
    r = resume(h.run_id, client=_client(FakeBackend("changed_models")), runs_root=tmp_path)
    assert await r.wait() == "finished"
    run = store.load_run(tmp_path, h.run_id)
    assert run["fingerprint"]["models"]["strong"] == "fake-strong-2" and run["mixed"] is False


async def test_concurrent_resume_second_refused_by_lock(synth, tmp_path):
    h = await _partial_run(synth, tmp_path)
    fb = FakeBackend("ok", delay=0.05)
    r1 = resume(h.run_id, client=_client(fb), runs_root=tmp_path)
    with pytest.raises(store.RunLockedError):
        resume(h.run_id, client=_client(FakeBackend("ok")), runs_root=tmp_path)
    assert await r1.wait() == "finished"
    assert fb.count == 7  # second resume sent nothing


async def test_stale_tmp_cleaned_on_resume(synth, tmp_path):
    h = await _partial_run(synth, tmp_path)
    tmp = store.run_dir(tmp_path, h.run_id) / "items" / ".x.json.tmp"
    tmp.write_text("{")
    r = resume(h.run_id, client=_client(FakeBackend("ok")), runs_root=tmp_path)
    await r.wait()
    assert not tmp.exists()


async def test_missing_dataset_failed_run_blocked_until_fixed(synth, tmp_path):
    meta = dataclasses.replace(synth.meta, data_required=True)
    ds = dataclasses.replace(synth, meta=meta)
    data = tmp_path / "data"
    h = start_run(ds, Selection(split="all"), base_url=URL, runs_root=tmp_path / "runs",
                  client=_client(FakeBackend("ok")), data_root=data)  # fmt: skip
    assert await h.wait() == "failed"
    runs = tmp_path / "runs"
    fb = FakeBackend("ok")
    with pytest.raises(ResumeError):
        resume(h.run_id, dataset=ds, client=_client(fb), runs_root=runs, data_root=data)
    assert store.load_run(runs, h.run_id)["state"] == "failed" and fb.count == 0
    assert not store.is_locked(runs, h.run_id)
    (data / meta.name).mkdir(parents=True)
    (data / meta.name / "download.json").write_text(json.dumps({"status": "ready"}))
    r = resume(h.run_id, dataset=ds, client=_client(fb), runs_root=runs, data_root=data)
    assert await r.wait() == "finished" and fb.count == 8
    assert "error" not in store.load_run(runs, h.run_id)
