import json
import re

import pytest
from fakes.fake_backend import FakeBackend

from iaudit_eval import paths, store
from iaudit_eval.client import AuditClient
from iaudit_eval.contracts import validate_request
from iaudit_eval.datasets import Unmapped, list_datasets, load
from iaudit_eval.engine import Selection, start_run

FORBIDDEN_SPEAKERS = {"alex1", "sam1", "clinician1"}
WINDOW = 8


@pytest.fixture(scope="module")
def ds():
    return load("synthetic")


def test_metadata():
    m = {x.name: x for x in list_datasets()}["synthetic"]
    assert m.data_required is False
    assert m.split_names() == ["dev", "test"]
    assert m.default_split in m.split_names()
    assert m.sources == ()
    assert m.license == {
        "name": "CC0-1.0", "redistributable": True, "contains_licensed_text": False,
    }  # fmt: skip
    assert "fictional" in m.description.lower()
    assert m.dataset_version and m.cluster_key
    assert m.slices == ("topic",)
    assert set(m.levels) == {"item", "section"}
    assert m.levels["item"]["positive"] in m.levels["item"]["labels"]


def test_shape(ds):
    items = ds.items("all")
    assert len(items) >= 20
    assert len({i.doc_id for i in items}) >= 7
    assert {i.split for i in items} == {"dev", "test"}
    assert sum(ds.split_sizes()[s] for s in ("dev", "test")) == len(items)
    for it in items:
        assert "topic" in it.meta
    # documents never straddle splits
    for doc in {i.doc_id for i in items}:
        assert len({i.split for i in items if i.doc_id == doc}) == 1
    golds = {ds.adapter.gold(i) for i in items}
    assert golds == set(ds.meta.levels["item"]["labels"])


def test_requests_validate(ds):
    for it in ds.items("all"):
        req = ds.adapter.to_request(it)
        assert validate_request(req) == [], it.id
        assert req["request_id"] == it.id


def _resp(status, *verdicts):
    return {"status": status, "claims": [{"verdict": v} for v in verdicts]}


def test_project(ds):
    it = ds.items("all")[0]
    a = ds.adapter
    assert a.project(_resp("complete", "supported", "out_of_scope"), it) == "clean"
    for bad in ("contradicted", "partially_supported", "insufficient_evidence"):
        assert a.project(_resp("complete", "supported", bad), it) == "flagged"
    for broken in ({}, {"claims": "x"}, _resp("partial", "supported"), _resp("complete")):
        with pytest.raises(Unmapped):
            a.project(broken, it)
    with pytest.raises(Unmapped):
        a.project({"status": "complete", "claims": [{"verdict": "weird"}]}, it)


def _words(s):
    return re.findall(r"[a-z0-9']+", s.lower())


def _strings(o):
    if isinstance(o, str):
        yield o
    elif isinstance(o, dict):
        for v in o.values():
            yield from _strings(v)
    elif isinstance(o, list):
        for v in o:
            yield from _strings(v)


def test_no_fewshot_overlap_or_speaker_ids(ds):
    pdir = paths.repo_root() / "eaudit" / "src" / "eaudit" / "prompts"
    files = sorted(pdir.glob("*_fewshot.json"))
    if not files:
        pytest.skip("backend few-shot files absent")
    grams = set()
    for f in files:
        for s in _strings(json.loads(f.read_text(encoding="utf-8"))):
            w = _words(s)
            grams.update(tuple(w[k : k + WINDOW]) for k in range(len(w) - WINDOW + 1))
    for it in ds.items("all"):
        req = ds.adapter.to_request(it)
        texts = [t["text"] for t in req["transcript"]] + [s["text"] for s in req["assessment"]]
        for t in texts:
            w = _words(t)
            for k in range(len(w) - WINDOW + 1):
                assert tuple(w[k : k + WINDOW]) not in grams, (it.id, t)
        speakers = {t["speaker"] for t in req["transcript"]}
        assert not speakers & FORBIDDEN_SPEAKERS
        assert not FORBIDDEN_SPEAKERS & set(_words(" ".join(texts)))


@pytest.mark.parametrize("concern", [
    "opinion_as_fact", "calculation_error", "meaning_shift", "unsupported_inference",
])
def test_taxonomy_cases_include_two_flags_and_a_faithful_near_miss(ds, concern):
    """Dropping or mislabelling a boundary case must leave a gap in offline coverage."""
    cases = {it.id: it for it in ds.items("all") if it.doc_id == f"doc-{concern}"}
    expected = {
        f"{concern}-flagged-a": "flagged",
        f"{concern}-flagged-b": "flagged",
        f"{concern}-clean": "clean",
    }
    assert {iid: ds.adapter.gold(it) for iid, it in cases.items()} == expected
    assert len({it.payload["summary"] for it in cases.values()}) == 3
    # Matched variants share the same source conversation, making the faithful
    # control useful for detecting false positives as well as missed flags.
    requests = [ds.adapter.to_request(it) for it in cases.values()]
    assert all(req["transcript"] == requests[0]["transcript"] for req in requests)
    assert len({it.split for it in cases.values()}) == 1


async def test_full_dataset_runs_offline_including_taxonomy_cases(ds, tmp_path):
    """Every public case passes through request conversion, persistence and projection."""
    backend = FakeBackend()
    async with AuditClient("http://fake", transport=backend.transport()) as client:
        run = start_run(
            ds, Selection(split="all"), base_url="http://fake", client=client,
            runs_root=tmp_path, on_finish=None,
        )
        assert await run.wait() == "finished"
    saved = {item["item_id"]: item for item in store.iter_items(tmp_path, run.run_id)}
    cases = {item.id: item for item in ds.items("all")}
    assert set(saved) == set(cases)
    assert len(saved) >= 20 and backend.audit_work == len(saved)
    for item_id, record in saved.items():
        assert record["status"] == "ok", item_id
        prediction = ds.adapter.project(record["response"], cases[item_id])
        pairs = ds.adapter.pairs(cases[item_id], ds.adapter.gold(cases[item_id]), prediction, None)
        assert [(pair.level, pair.pred) for pair in pairs] == [
            ("item", "flagged"), ("section", True),
        ]
