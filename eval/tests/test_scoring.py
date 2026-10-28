import asyncio
import json
import re
import textwrap

import pytest
from fakes.fake_backend import FakeBackend

from iaudit_eval import store
from iaudit_eval.client import AuditClient
from iaudit_eval.datasets import load
from iaudit_eval.engine import Selection, start_run
from iaudit_eval.scoring import ScoringError, score

URL = "http://fake"


async def _nosleep(_s):
    return None


def _make_run(tmp_path, mode="ok", **kw):
    async def go():
        fb = FakeBackend(mode)
        client = AuditClient(URL, transport=fb.transport(), sleep=_nosleep)
        h = start_run(load("synthetic"), Selection(split="all"), base_url=URL,
                      runs_root=tmp_path, client=client, **kw)  # fmt: skip
        await h.wait()
        return h.run_id

    return asyncio.run(go())


def _entry(rep, metric, level, policy, sl=None):
    hits = [e for e in rep["entries"] if (e["metric"], e["level"], e["policy"]) == (metric, level, policy)
            and e["slice"] == (sl or {})]  # fmt: skip
    assert len(hits) == 1, (metric, level, policy, sl, len(hits))
    return hits[0]


def _norm(raw: bytes) -> bytes:
    return re.sub(rb'"at": "[^"]*"', b'"at": "X"', raw)


# ---------- synthetic two-level, real run ----------

def test_synthetic_two_levels(tmp_path):
    rid = _make_run(tmp_path, tags={"contamination": "none"})
    rep = score(rid, runs_root=tmp_path)
    assert rep["run_id"] == rid and rep["dataset"] == "synthetic"
    assert rep["primary_policy"] == "failures_count_wrong"
    assert rep["items"] == {"selected": 8, "scored": 8, "failed": 0, "not_run": 0}
    assert rep["run"]["complete"] is True and rep["run"]["state"] == "finished"
    assert rep["run"]["tags"] == {"contamination": "none"}
    assert rep["failures"]["by_reason"] == {"item_failed": 0, "unmapped": 0, "unresolved": 0}
    assert {e["level"] for e in rep["entries"]} == {"item", "section"}
    # fake backend flags every item: 5 flagged, 3 clean -> recall 1, balanced accuracy 0.5
    assert _entry(rep, "recall", "item", "primary")["value"] == 1.0
    assert _entry(rep, "balanced_accuracy", "item", "primary")["value"] == 0.5
    assert _entry(rep, "recall", "section", "primary")["n"] == 5
    assert _entry(rep, "balanced_accuracy", "item", "primary", {"topic": "clinical"})
    assert _entry(rep, "failure_rate", "item", "none")["value"] == 0.0
    assert not [e for e in rep["entries"] if e["metric"] == "recall_by_type"]
    assert [e["policy"] for e in rep["entries"] if e["metric"] == "failure_rate"] == ["none"] * 6
    assert (tmp_path / rid / "metrics.json").is_file()
    rows = json.loads((tmp_path / rid / "item_rows.json").read_text())["rows"]
    assert [r["item_id"] for r in rows] == sorted(r["item_id"] for r in rows) and len(rows) == 8
    assert {r["gold"] for r in rows} == {"clean", "flagged"} and {r["pred"] for r in rows} == {"flagged"}
    assert {r["match"] for r in rows} == {True, False} and {r["status"] for r in rows} == {"ok"}
    scored = rep["scored"]
    assert scored["metrics_version"] and isinstance(scored["git_dirty"], bool) and scored["git_commit"]


def test_idempotent_byte_identical_except_scored_at(tmp_path):
    rid = _make_run(tmp_path)
    score(rid, runs_root=tmp_path)
    m1 = (tmp_path / rid / "metrics.json").read_bytes()
    r1 = (tmp_path / rid / "item_rows.json").read_bytes()
    score(rid, runs_root=tmp_path)
    assert _norm((tmp_path / rid / "metrics.json").read_bytes()) == _norm(m1)
    assert (tmp_path / rid / "item_rows.json").read_bytes() == r1


def test_aborted_run_not_run_and_incomplete(tmp_path):
    rid = _make_run(tmp_path)
    files = sorted((tmp_path / rid / "items").glob("*.json"))
    for f in files[:3]:
        f.unlink()
    store.update_run(tmp_path, rid, state="aborted")
    rep = score(rid, runs_root=tmp_path)
    assert rep["items"] == {"selected": 8, "scored": 5, "failed": 0, "not_run": 3}
    assert rep["run"]["complete"] is False and rep["run"]["state"] == "aborted"
    assert rep["failures"]["by_reason"]["item_failed"] == 0  # not-run is not a failure
    assert _entry(rep, "failure_rate", "item", "none")["value"] == 0.0
    assert len(json.loads((tmp_path / rid / "item_rows.json").read_text())["rows"]) == 5


def test_all_items_failed_count_wrong(tmp_path):
    rid = _make_run(tmp_path, "500")
    rep = score(rid, runs_root=tmp_path)
    assert rep["items"] == {"selected": 8, "scored": 0, "failed": 8, "not_run": 0}
    assert rep["failures"]["by_reason"]["item_failed"] == 8
    assert _entry(rep, "recall", "item", "primary")["value"] == 0.0
    assert _entry(rep, "recall", "item", "secondary")["value"] is None
    assert _entry(rep, "recall", "item", "secondary")["ci_status"] == "undefined"
    assert _entry(rep, "failure_rate", "item", "none")["value"] == 1.0
    assert _entry(rep, "coverage", "item", "none")["value"] == 0.0
    rows = json.loads((tmp_path / rid / "item_rows.json").read_text())["rows"]
    assert {r["status"] for r in rows} == {"failed"} and {r["match"] for r in rows} == {None}
    assert {r["pred"] for r in rows} == {None}


# ---------- tiny hand-built datasets ----------

_ADAPTER = '''
from iaudit_eval.datasets import Item, Unmapped
from iaudit_eval.metrics.pair import Pair

ITEMS = [("a1", "d1", "x"), ("a2", "d1", "y"), ("b1", "d2", "x"), ("b2", "d2", None),
         ("c1", "d3", "y"), ("c2", "d3", "x"), ("e1", "d4", "y"), ("e2", "d5", "x")]
GOLD = {"a1": True, "a2": False, "b1": True, "b2": False, "c1": True, "c2": False,
        "e1": True, "e2": False}


class A:
    def __init__(self, d):
        self.d = d

    def items(self, split):
        out = []
        for i, doc, g in ITEMS:
            meta = {"grp": g} if g else {}
            out.append(Item(i, doc, "all", {}, meta))
        return out

    def to_request(self, item):
        return {}

    def gold(self, item):
        if MISSING:
            raise FileNotFoundError("no gold on disk")
        return GOLD[item.id]

    def project(self, response, item):
        if response.get("bad"):
            raise Unmapped("nope")
        return response["v"]
EXTRA
'''

_META = {
    "name": "tiny", "product": "eaudit", "dataset_version": "7", "kind": "adapter",
    "splits": [{"name": "all"}], "default_split": "all", "cluster_key": "doc",
    "slices": ["grp"], "levels": {"item": {"labels": [False, True], "positive": True}},
}  # fmt: skip


def _tiny(tmp_path, *, meta=None, extra="", missing=False, files=None):
    root = tmp_path / "datasets"
    d = root / "eaudit/tiny"
    d.mkdir(parents=True)
    (d / "metadata.json").write_text(json.dumps({**_META, **(meta or {})}))
    src = _ADAPTER.replace("EXTRA", textwrap.indent(textwrap.dedent(extra), "    "))
    (d / "adapter.py").write_text(src.replace("MISSING", repr(missing)) + "\n\ndef create(d):\n    return A(d)\n")
    for name, text in (files or {}).items():
        (d / name).write_text(text)
    return root


def _tiny_run(tmp_path, results, *, state="finished", **run):
    rroot = tmp_path / "runs"
    ids = [r[0] for r in results]
    rid = store.create_run(rroot, {"dataset": "tiny", "dataset_version": "7", "split": "all",
                                   "item_ids": ids, "run_id": "r1", **run})  # fmt: skip
    for iid, doc, status, resp in results:
        if status is None:
            continue
        store.write_item(rroot, rid, {"item_id": iid, "doc_id": doc, "status": status,
                                      "response": resp, "response_status": "complete",
                                      "failure": None if status == "ok" else {"code": "x"}})  # fmt: skip
    store.update_run(rroot, rid, state=state)
    return rroot, rid


def _all_ok(pred_by_id=None):
    doc = {"a1": "d1", "a2": "d1", "b1": "d2", "b2": "d2", "c1": "d3", "c2": "d3", "e1": "d4", "e2": "d5"}
    gold = {"a1": True, "a2": False, "b1": True, "b2": False, "c1": True, "c2": False, "e1": True, "e2": False}
    pred = pred_by_id or gold
    return [(i, doc[i], "ok", {"v": pred[i]}) for i in doc]


def test_unmapped_and_item_failed_and_slices(tmp_path):
    res = _all_ok()
    res[1] = ("a2", "d1", "ok", {"bad": True})  # unmapped (gold False -> flipped to True)
    res[2] = ("b1", "d2", "failed", None)  # item_failed (gold True -> flipped to False)
    res[3] = ("b2", "d2", None, None)  # not run
    rroot, rid = _tiny_run(tmp_path, res, mapping_version="m2", tags={"t": "1"})
    rep = score(rid, runs_root=rroot, datasets_root=_tiny(tmp_path))
    assert rep["items"] == {"selected": 8, "scored": 5, "failed": 2, "not_run": 1}
    assert rep["failures"]["by_reason"] == {"item_failed": 1, "unmapped": 1, "unresolved": 0}
    assert rep["run"] == {"state": "finished", "complete": False, "mapping_version": "m2",
                          "tags": {"t": "1"}}  # fmt: skip
    # one-way slice: items without meta 'grp' appear only in the all slice (b2 not run)
    assert [e for e in rep["entries"] if e["slice"] == {"grp": "x"}]
    assert not [e for e in rep["entries"] if "grp" in e["slice"] and e["slice"]["grp"] is None]
    assert _entry(rep, "failure_rate", "item", "none")["n"] == 7
    row = {r["item_id"]: r for r in json.loads((rroot / rid / "item_rows.json").read_text())["rows"]}
    assert row["a2"]["status"] == "unmapped" and row["b1"]["status"] == "failed"
    assert row["a1"]["match"] is True and "b2" not in row


def test_pool_all_false_and_custom_metrics_alias_params(tmp_path):
    meta = {"pool_all": False, "metrics": [
        {"name": "rec_x", "fn": "recall_by_type", "level": "item", "params": {"tag_key": "grp", "tag": "x"}},
        {"name": "unmapped_rate", "fn": "failure_rate", "level": "item", "params": {"reason": "unmapped"}},
    ]}  # fmt: skip
    rroot, rid = _tiny_run(tmp_path, _all_ok())
    rep = score(rid, runs_root=rroot, datasets_root=_tiny(tmp_path, meta=meta))
    assert all(e["slice"] != {} for e in rep["entries"])
    names = {e["metric"] for e in rep["entries"]}
    assert names == {"rec_x", "unmapped_rate"}


def test_references_and_report_extra_pass_through(tmp_path):
    refs = {"rows": [{"source": "paper", "label": "GPT", "metric": "recall", "level": "item",
                      "slice": {}, "value": 0.5, "note": "n"}], "caveats": ["not comparable"]}  # fmt: skip
    extra = "def report_extra(self, run, runs_root):\n    return {'seen': run['run_id']}\n"
    ds = _tiny(tmp_path, meta={"references": "references.json"}, extra=extra,
               files={"references.json": json.dumps(refs)})  # fmt: skip
    rroot, rid = _tiny_run(tmp_path, _all_ok())
    rep = score(rid, runs_root=rroot, datasets_root=ds)
    assert rep["references"] == refs["rows"] and rep["reference_caveats"] == ["not comparable"]
    assert rep["dataset_extra"] == {"seen": "r1"}


def test_malformed_references_fail_loudly_no_files(tmp_path):
    bad = {"rows": [{"source": "p", "label": "l", "metric": "recall", "level": "item",
                     "slice": {}, "value": "high"}]}  # fmt: skip
    for text in (json.dumps(bad), "{not json", json.dumps([1])):
        sub = tmp_path / str(abs(hash(text)))
        sub.mkdir()
        ds = _tiny(sub, meta={"references": "references.json"}, files={"references.json": text})
        rroot, rid = _tiny_run(sub, _all_ok())
        with pytest.raises(ValueError):
            score(rid, runs_root=rroot, datasets_root=ds)
        assert not (rroot / rid / "metrics.json").exists()
        assert not (rroot / rid / "item_rows.json").exists()


def test_missing_gold_clear_error_no_partial_file(tmp_path):
    rroot, rid = _tiny_run(tmp_path, _all_ok())
    with pytest.raises(ScoringError, match="gold"):
        score(rid, runs_root=rroot, datasets_root=_tiny(tmp_path, missing=True))
    assert not list((rroot / rid).glob("metrics.json")) and not list((rroot / rid).glob("item_rows.json"))
    assert not list((rroot / rid).glob(".*.tmp"))


def test_adapter_item_row_hook_and_unit_failures(tmp_path):
    extra = '''
    def item_row(self, item, gold, pred, failure):
        return {"item_id": item.id, "status": "failed" if failure else "ok", "gold": "G",
                "pred": None if failure else "P", "match": None, "detail": {"k": 1}}
    '''
    rroot, rid = _tiny_run(tmp_path, _all_ok())
    score(rid, runs_root=rroot, datasets_root=_tiny(tmp_path, extra=extra))
    rows = json.loads((rroot / rid / "item_rows.json").read_text())["rows"]
    assert {r["gold"] for r in rows} == {"G"} and rows[0]["detail"] == {"k": 1}


def test_default_set_skips_param_needing_builtins(tmp_path):
    rroot, rid = _tiny_run(tmp_path, _all_ok())
    rep = score(rid, runs_root=rroot, datasets_root=_tiny(tmp_path))
    names = {e["metric"] for e in rep["entries"]}
    assert names == {"balanced_accuracy", "precision", "recall", "f1", "failure_rate", "coverage"}
    assert _entry(rep, "recall", "item", "primary")["value"] == 1.0
    assert _entry(rep, "recall", "item", "primary")["n_clusters"] == 5


def test_unknown_run_is_scoring_error(tmp_path):
    with pytest.raises(ScoringError):
        score("nope", runs_root=tmp_path)


# ---------- auto-score hook (R8) ----------

def test_auto_score_on_finish_writes_metrics(tmp_path):
    rid = _make_run(tmp_path)
    assert (tmp_path / rid / "metrics.json").is_file()
    assert (tmp_path / rid / "item_rows.json").is_file()


def test_on_finish_none_disables_auto_score(tmp_path):
    rid = _make_run(tmp_path, on_finish=None)
    assert not (tmp_path / rid / "metrics.json").exists()


def test_scoring_error_leaves_state_and_rescorable(tmp_path, monkeypatch, caplog):
    import iaudit_eval.scoring as scoring

    real = scoring.score

    before = []

    def boom(run_id, **kwargs):
        before.append(store.load_run(kwargs["runs_root"], run_id))
        raise RuntimeError("secret text")

    monkeypatch.setattr(scoring, "score", boom)
    rid = _make_run(tmp_path)
    run = store.load_run(tmp_path, rid)
    assert run["state"] == "finished"
    assert before == [run]  # state and all persisted run fields survive the error
    assert "finish_hook_error" in caplog.text and "RuntimeError" in caplog.text
    assert "secret text" not in caplog.text
    assert not (tmp_path / rid / "metrics.json").exists()
    monkeypatch.setattr(scoring, "score", real)
    assert real(rid, runs_root=tmp_path)["run_id"] == rid
    assert (tmp_path / rid / "metrics.json").is_file()


def test_auto_score_on_resume(tmp_path):
    from iaudit_eval.engine import resume

    rid = _make_run(tmp_path, on_finish=None)

    async def go():
        fb = FakeBackend("ok")
        client = AuditClient(URL, transport=fb.transport(), sleep=_nosleep)
        h = resume(rid, runs_root=tmp_path, client=client)
        await h.wait()

    asyncio.run(go())
    assert (tmp_path / rid / "metrics.json").is_file()


def test_custom_finish_hook_replaces_auto_score(tmp_path):
    finished = []

    async def finish(run_id):
        finished.append((run_id, store.load_run(tmp_path, run_id)["state"]))

    rid = _make_run(tmp_path, on_finish=finish)
    assert finished == [(rid, "finished")]
    assert not (tmp_path / rid / "metrics.json").exists()
