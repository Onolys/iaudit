import json
import shutil

import pytest
from test_scoring import _make_run

from iaudit_eval.compare import CompareError, compare
from iaudit_eval.metrics.report import ReportSchemaError, validate_compare
from iaudit_eval.scoring import score

ALL = [
    "garden-clean", "garden-roof", "garden-weekend", "physio-adherence",
    "physio-clean", "physio-pain", "sleep-clean", "sleep-meds",
]  # fmt: skip


def _items(root, rid):
    return root / rid / "items"


@pytest.fixture
def pair_of_runs(tmp_path):
    a = _make_run(tmp_path)
    b = _make_run(tmp_path)
    _items(tmp_path, a).joinpath("sleep-meds.json").unlink()  # b only
    _items(tmp_path, b).joinpath("garden-roof.json").unlink()  # a only
    f = _items(tmp_path, b) / "physio-pain.json"  # shared; failed in b
    rec = json.loads(f.read_text())
    rec.pop("response", None)
    rec["status"] = "failed"
    f.write_text(json.dumps(rec))
    return tmp_path, a, b


def _restricted_copy(root, rid, keep, name):
    shutil.copytree(root / rid, root / name)
    for f in (root / name / "items").glob("*.json"):
        if f.stem not in keep:
            f.unlink()
    (root / name / "metrics.json").unlink(missing_ok=True)
    (root / name / "item_rows.json").unlink(missing_ok=True)
    run = json.loads((root / name / "run.json").read_text())
    run["run_id"] = name
    (root / name / "run.json").write_text(json.dumps(run))
    return name


def test_counts_and_validation(pair_of_runs):
    root, a, b = pair_of_runs
    rep = compare(a, b, runs_root=root)
    validate_compare(rep)
    assert rep["schema_version"] == "0.0.1"
    assert (rep["run_a"], rep["run_b"], rep["dataset"]) == (a, b, "synthetic")
    assert rep["n_shared"] == 6 and rep["n_a_only"] == 1 and rep["n_b_only"] == 1
    assert rep["n_clusters_shared"] == 3
    assert rep["warnings"] == []
    json.dumps(rep)


def test_deltas_equal_rescoring_intersection(pair_of_runs):
    root, a, b = pair_of_runs
    shared = set(ALL) - {"sleep-meds", "garden-roof"}
    ra = score(_restricted_copy(root, a, shared, "ra"), runs_root=root)
    rb = score(_restricted_copy(root, b, shared, "rb"), runs_root=root)
    rep = compare(a, b, runs_root=root)
    key = lambda e: (e["metric"], e["level"], e["policy"], json.dumps(e["slice"], sort_keys=True))  # noqa: E731
    ea = {key(e): e for e in ra["entries"]}
    eb = {key(e): e for e in rb["entries"]}
    assert rep["deltas"]
    for d in rep["deltas"]:
        k = key(d)
        assert k in ea and k in eb
        for side, e in (("a", ea[k]), ("b", eb[k])):
            assert d[side] == {"value": e["value"], "n": e["n"], "ci": e["ci"]}
        if e["value"] is not None and ea[k]["value"] is not None:
            assert d["delta"] == pytest.approx(eb[k]["value"] - ea[k]["value"])
        else:
            assert d["delta"] is None
        assert d["delta_ci"] is None  # 3 clusters -> R6 few_clusters
        assert d["ci_status"] in ("few_clusters", "undefined")
    # physio-pain failed in b: gold flagged, binary wrong label -> recall drops
    d = next(x for x in rep["deltas"] if (x["metric"], x["level"], x["policy"], x["slice"]) == ("recall", "item", "primary", {}))
    assert d["a"]["value"] == 1.0 and d["b"]["value"] < 1.0 and d["delta"] < 0


def test_disagreements_only_differing_pairs(pair_of_runs):
    root, a, b = pair_of_runs
    rep = compare(a, b, runs_root=root)
    dis = rep["disagreements"]
    assert [d["item_id"] for d in dis] == ["physio-pain"]
    d = dis[0]
    assert d["cluster"] == "doc-physio"
    assert d["pairs"]
    for p in d["pairs"]:
        assert set(p) == {"level", "unit", "gold", "a", "b"} and p["a"] != p["b"]
    item = [p for p in d["pairs"] if p["level"] == "item"][0]
    assert item["gold"] == "flagged" and item["a"] == "flagged" and item["b"] == "FAILED"


def test_different_datasets_error(pair_of_runs):
    root, a, b = pair_of_runs
    run = json.loads((root / b / "run.json").read_text())
    run["dataset"] = "other"
    (root / b / "run.json").write_text(json.dumps(run))
    with pytest.raises(CompareError):
        compare(a, b, runs_root=root)


def test_version_warnings(pair_of_runs):
    root, a, b = pair_of_runs
    run = json.loads((root / b / "run.json").read_text())
    run["dataset_version"] = "zzz"
    run["mapping_version"] = "zzz"
    (root / b / "run.json").write_text(json.dumps(run))
    rep = compare(a, b, runs_root=root)
    validate_compare(rep)
    assert len(rep["warnings"]) == 2
    assert any("dataset_version" in w for w in rep["warnings"])
    assert any("mapping_version" in w for w in rep["warnings"])


def test_zero_overlap(tmp_path):
    a = _make_run(tmp_path)
    b = _make_run(tmp_path)
    for f in _items(tmp_path, a).glob("*.json"):
        if f.stem in ALL[:4]:
            f.unlink()
    for f in _items(tmp_path, b).glob("*.json"):
        if f.stem in ALL[4:]:
            f.unlink()
    rep = compare(a, b, runs_root=tmp_path)
    validate_compare(rep)
    assert rep["deltas"] == [] and rep["disagreements"] == []
    assert (rep["n_shared"], rep["n_a_only"], rep["n_b_only"], rep["n_clusters_shared"]) == (0, 4, 4, 0)


def test_unknown_run_errors(tmp_path):
    a = _make_run(tmp_path)
    with pytest.raises(CompareError):
        compare(a, "nope", runs_root=tmp_path)


def test_compare_does_not_write(pair_of_runs):
    root, a, b = pair_of_runs
    before = sorted(p.name for p in (root / a).iterdir())
    compare(a, b, runs_root=root)
    assert sorted(p.name for p in (root / a).iterdir()) == before


def test_validate_compare_rejects_bad():
    with pytest.raises(ReportSchemaError):
        validate_compare({"schema_version": "0.0.1"})


def test_nonmatching_saved_comparison_is_schema_error(pair_of_runs):
    root, a, b = pair_of_runs
    report = compare(a, b, runs_root=root)
    report["schema_version"] = "9.8.7"
    with pytest.raises(ReportSchemaError, match="schema_version"):
        validate_compare(report)
