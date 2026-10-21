"""metrics.schema.json / item_rows.schema.json validation (03-metrics-scoring Task 6)."""

import copy

import pytest

from iaudit_eval.metrics.report import (
    METRICS_SCHEMA_VERSION,
    ReportSchemaError,
    validate_item_rows,
    validate_metrics,
)


def good_report():
    return {
        "schema_version": "1.0.0", "run_id": "r1", "dataset": "synthetic",
        "dataset_version": "1", "primary_policy": "failures_count_wrong",
        "scored": {"at": "2026-10-21T00:00:00Z", "metrics_version": "1.0.0",
                   "git_commit": "abc123", "git_dirty": False},
        "bootstrap": {"method": "cluster_percentile", "resamples": 1000, "seed": 0, "level": 0.95},
        "run": {"state": "finished", "complete": True, "mapping_version": None, "tags": {"x": 1}},
        "dataset_extra": {"anything": [1, 2]}, "reference_caveats": ["note"],
        "items": {"selected": 3, "scored": 2, "failed": 1, "not_run": 0},
        "failures": {"by_reason": {"item_failed": 1, "custom_reason": 2}},
        "entries": [
            {"metric": "f1", "level": "item", "policy": "primary", "slice": {"dataset": "a", "k": 1},
             "value": 0.5, "n": 3, "n_clusters": 3, "ci": None, "ci_status": "few_clusters",
             "impl": "core"},
            {"metric": "f1", "level": "item", "policy": "none", "slice": {},
             "value": None, "n": 0, "n_clusters": 0, "ci": None, "ci_status": "undefined"},
            {"metric": "f1", "level": "item", "policy": "secondary", "slice": {},
             "value": 0.5, "n": 9, "n_clusters": 9, "ci": [0.1, 0.9], "ci_status": "ok"},
        ],
        "references": [{"source": "paper", "label": "GPT", "metric": "f1", "level": "item",
                        "slice": {}, "value": 0.7, "note": "n"}],
    }


def good_rows():
    return {"schema_version": "1.0.0", "run_id": "r1", "rows": [
        {"item_id": "a", "status": "ok", "gold": "True", "pred": "True", "match": True},
        {"item_id": "b", "label": "B", "status": "failed", "gold": "True", "pred": None,
         "match": None, "outcome": "timeout", "detail": {"s": [1]}},
        {"item_id": "c", "status": "unmapped", "gold": "x", "pred": "y", "match": False},
    ]}


def test_valid_report_and_rows():
    validate_metrics(good_report())
    validate_item_rows(good_rows())
    assert METRICS_SCHEMA_VERSION == "1.0.0"


def test_state_values():
    for s in ("running", "finished", "aborted_cost", "aborted", "failed", "interrupted"):
        r = good_report()
        r["run"]["state"] = s
        validate_metrics(r)


def mutate(fn):
    r = good_report()
    fn(r)
    return r


BAD_REPORTS = {
    "bad_state": lambda r: r["run"].update(state="weird"),
    "bad_policy": lambda r: r["entries"][0].update(policy="x"),
    "bad_ci_status": lambda r: r["entries"][0].update(ci_status="meh"),
    "ci_wrong_len": lambda r: r["entries"][2].update(ci=[0.1]),
    "extra_entry_key": lambda r: r["entries"][0].update(extra=1),
    "missing_n_clusters": lambda r: r["entries"][0].pop("n_clusters"),
    "slice_nested": lambda r: r["entries"][0].update(slice={"a": {"b": 1}}),
    "missing_commit": lambda r: r["scored"].pop("git_commit"),
    "missing_version": lambda r: r.pop("schema_version"),
    "bad_version": lambda r: r.update(schema_version="2.0.0"),
    "neg_count": lambda r: r["items"].update(failed=-1),
    "by_reason_non_int": lambda r: r["failures"]["by_reason"].update(x="a"),
    "ref_has_ci": lambda r: r["references"][0].update(ci=[0, 1]),
    "ref_has_n": lambda r: r["references"][0].update(n=5),
    "ref_missing_value": lambda r: r["references"][0].pop("value"),
    "ref_missing_source": lambda r: r["references"][0].pop("source"),
    "ref_null_value_str": lambda r: r["references"][0].update(value="0.7"),
    "caveats_not_list": lambda r: r.update(reference_caveats="x"),
    "extra_top": lambda r: r.update(bogus=1),
}


@pytest.mark.parametrize("name", sorted(BAD_REPORTS))
def test_bad_report_fails(name):
    r = mutate(BAD_REPORTS[name])
    with pytest.raises(ReportSchemaError):
        validate_metrics(r)


BAD_ROWS = {
    "bad_status": lambda d: d["rows"][0].update(status="meh"),
    "missing_gold": lambda d: d["rows"][0].pop("gold"),
    "gold_not_str": lambda d: d["rows"][0].update(gold=True),
    "match_str": lambda d: d["rows"][0].update(match="yes"),
    "extra_key": lambda d: d["rows"][0].update(n=1),
    "detail_not_obj": lambda d: d["rows"][1].update(detail=[1]),
    "rows_missing": lambda d: d.pop("rows"),
    "not_wrapper": lambda d: d.update(rows="x"),
}


@pytest.mark.parametrize("name", sorted(BAD_ROWS))
def test_bad_rows_fail(name):
    d = copy.deepcopy(good_rows())
    BAD_ROWS[name](d)
    with pytest.raises(ReportSchemaError):
        validate_item_rows(d)


def test_error_lists_paths_not_values():
    r = good_report()
    r["entries"][0]["ci_status"] = "SECRET-VALUE"
    with pytest.raises(ReportSchemaError) as ei:
        validate_metrics(r)
    assert "entries/0/ci_status" in str(ei.value)
    assert "SECRET-VALUE" not in str(ei.value)
