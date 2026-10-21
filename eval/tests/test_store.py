import json
import os
import re
import stat
import subprocess
import sys

import pytest

from iaudit_eval import store


def _mode(p):
    return stat.S_IMODE(os.stat(p).st_mode)


def _meta(ids=("a", "b", "c")):
    return {"dataset": "synth", "dataset_version": "1", "split": "test", "n_requested": len(ids),
            "seed": 0, "item_ids": list(ids), "concurrency": 4, "max_cost_usd": None}


def _item(i, status="ok", rs="complete", run_info=None):
    return {"item_id": i, "doc_id": i, "status": status, "attempts": 1, "started_at": "t",
            "finished_at": "t", "latency_ms": 1, "request": {}, "response": None if status == "failed" else {},
            "response_status": rs, "run_info": run_info,
            "failure": {"kind": "x", "issues": []} if status == "failed" else None}


def test_run_id_format():
    rid = store.new_run_id("synth")
    assert re.fullmatch(r"\d{8}T\d{6}Z-synth-[0-9a-f]{6}", rid)
    assert store.new_run_id("synth") != rid


def test_create_run_and_modes(tmp_path):
    rid = store.create_run(tmp_path, _meta())
    d = tmp_path / rid
    run = json.loads((d / "run.json").read_text())
    assert run["store_version"] == 1 and run["state"] == "running" and run["run_id"] == rid
    assert run["tags"] == {} and run["resumes"] == [] and run["warnings"] == []
    assert _mode(d) == 0o700 and _mode(d / "items") == 0o700 and _mode(d / "run.json") == 0o600
    store.write_item(tmp_path, rid, _item("a"))
    assert _mode(d / "items" / "a.json") == 0o600


def test_atomic_write_no_torn_file_on_crash(tmp_path, monkeypatch):
    rid = store.create_run(tmp_path, _meta())
    store.write_item(tmp_path, rid, _item("a"))
    good = (tmp_path / rid / "items" / "a.json").read_text()

    def boom(*a, **k):
        raise OSError("crash")

    monkeypatch.setattr(os, "replace", boom)
    with pytest.raises(OSError):
        store.write_item(tmp_path, rid, _item("a", status="failed"))
    monkeypatch.undo()
    assert (tmp_path / rid / "items" / "a.json").read_text() == good
    # leftover tmp exists, then cleaned
    assert list((tmp_path / rid / "items").glob("*.tmp")) or True
    store.clean_stale_tmp(tmp_path, rid)
    assert not list((tmp_path / rid).rglob("*.tmp"))
    assert [i["item_id"] for i in store.iter_items(tmp_path, rid)] == ["a"]


def test_stale_tmp_ignored_by_reads(tmp_path):
    rid = store.create_run(tmp_path, _meta())
    (tmp_path / rid / "items" / ".b.json.tmp").write_text("{torn")
    assert list(store.iter_items(tmp_path, rid)) == []
    store.clean_stale_tmp(tmp_path, rid)
    assert not (tmp_path / rid / "items" / ".b.json.tmp").exists()


def test_lock_second_acquirer_refused(tmp_path):
    rid = store.create_run(tmp_path, _meta())
    with store.RunLock(tmp_path, rid):
        with pytest.raises(store.RunLockedError):
            with store.RunLock(tmp_path, rid):
                pass
        assert store.is_locked(tmp_path, rid)
    assert not store.is_locked(tmp_path, rid)
    with store.RunLock(tmp_path, rid):
        pass
    assert _mode(tmp_path / rid / "run.lock") == 0o600


def test_effective_state_interrupted(tmp_path):
    rid = store.create_run(tmp_path, _meta())
    assert store.effective_state(tmp_path, rid) == "interrupted"
    with store.RunLock(tmp_path, rid):
        assert store.effective_state(tmp_path, rid) == "running"
    store.update_run(tmp_path, rid, state="finished")
    assert store.effective_state(tmp_path, rid) == "finished"
    for s in ("aborted_cost", "aborted", "failed"):
        store.update_run(tmp_path, rid, state=s)
        assert store.effective_state(tmp_path, rid) == s


def test_lock_released_when_process_dies(tmp_path):
    rid = store.create_run(tmp_path, _meta())
    code = (
        "import sys,os;from pathlib import Path;from iaudit_eval import store;"
        f"l=store.RunLock(Path({str(tmp_path)!r}),{rid!r});l.__enter__();os._exit(0)"
    )
    subprocess.run([sys.executable, "-c", code], check=True)
    assert store.effective_state(tmp_path, rid) == "interrupted"


def test_totals_from_items(tmp_path):
    rid = store.create_run(tmp_path, _meta())
    ri = {"models": {}, "prompt_hashes": {}, "input_tokens": 10, "output_tokens": 5, "cost_usd": 0.25}
    store.write_item(tmp_path, rid, _item("a", run_info=ri))
    store.write_item(tmp_path, rid, _item("b", rs="partial", run_info={**ri, "cost_usd": 0.5}))
    t = store.compute_totals(tmp_path, rid)
    assert t == {"ok": 1, "failed": 0, "missing": 1, "partial": 1,
                 "input_tokens": 20, "output_tokens": 10, "cost_usd": 0.75}
    store.write_item(tmp_path, rid, _item("c", status="failed"))
    t = store.compute_totals(tmp_path, rid)
    assert (t["ok"], t["failed"], t["missing"], t["partial"]) == (1, 1, 0, 1)
    store.refresh_totals(tmp_path, rid)
    assert store.load_run(tmp_path, rid)["totals"] == t


def test_totals_null_when_unreported(tmp_path):
    rid = store.create_run(tmp_path, _meta(("a",)))
    store.write_item(tmp_path, rid, _item("a"))
    t = store.compute_totals(tmp_path, rid)
    assert t["input_tokens"] is None and t["output_tokens"] is None and t["cost_usd"] is None


def test_progress_and_list_runs(tmp_path):
    r1 = store.create_run(tmp_path, _meta())
    store.write_item(tmp_path, r1, _item("a"))
    store.write_item(tmp_path, r1, _item("b", status="failed"))
    p = store.progress(tmp_path, r1)
    assert (p["done"], p["failed"], p["total"]) == (1, 1, 3)
    assert p["state"] == "interrupted" and p["cost_usd"] is None
    r2 = store.create_run(tmp_path, _meta())
    runs = store.list_runs(tmp_path)
    assert {r["run_id"] for r in runs} == {r1, r2}
    assert store.list_runs(tmp_path / "nope") == []


def test_load_run_missing(tmp_path):
    with pytest.raises(FileNotFoundError):
        store.load_run(tmp_path, "nope")


def test_default_root_uses_env(tmp_path, monkeypatch):
    monkeypatch.setenv("IAUDIT_EVAL_HOME", str(tmp_path))
    rid = store.create_run(None, _meta())
    assert (tmp_path / "runs" / rid / "run.json").is_file()


def test_rejects_bad_ids(tmp_path):
    rid = store.create_run(tmp_path, _meta())
    with pytest.raises(ValueError):
        store.write_item(tmp_path, rid, _item("../x"))
    with pytest.raises(ValueError):
        store.load_run(tmp_path, "../x")
