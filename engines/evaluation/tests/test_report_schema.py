"""report.schema.json (SP03 R7): fixtures validate, malformed docs are rejected, the schema is
generated from the models and in sync, quotes in fixtures are real transcript substrings."""

import copy
import json

import pytest
from conftest import REPORT_NAMES, SCHEMA_PATH, load
from jsonschema import Draft202012Validator
from onolys_core.transcript import Transcript
from paudit.result import PauditResult
from pydantic import ValidationError

from onolys_evaluation.report import (
    SCHEMA_VERSION,
    Report,
    report_schema,
    schema_text,
)

pytestmark = pytest.mark.unit


@pytest.fixture(scope="module")
def validator():
    schema = json.loads(SCHEMA_PATH.read_text())
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema)


def test_three_fixture_reports_validate_in_schema_and_models(validator, report_doc):
    assert list(validator.iter_errors(report_doc)) == []
    model = Report.model_validate(report_doc)
    assert json.loads(model.model_dump_json(exclude_none=False)) is not None


def test_fixture_variants_cover_full_partial_none():
    full, partial, none = (load(f"{n}.json") for n in REPORT_NAMES)
    assert full["header"]["has_clinician_rating"] is True
    assert full["header"]["rating_coverage"]["rated"] == full["header"]["rating_coverage"]["total"]
    assert partial["header"]["has_clinician_rating"] is True
    cov = partial["header"]["rating_coverage"]
    assert 0 < cov["rated"] < cov["total"]
    assert none["header"]["has_clinician_rating"] is False
    assert none["reasons_audit"]["status"] == "skipped"
    assert none["aggregates"]["avg_abs_global_difference"] is None
    assert none["aggregates"]["within_one_share"] is None
    assert all(r["clinician"]["value"] is None for r in none["scorecard"])
    assert none["tips"] and none["method"]["statement"]


def _rm(path):
    def f(d):
        node = d
        for p in path[:-1]:
            node = node[p]
        del node[path[-1]]

    return f


MUTATIONS = {
    "missing_header": _rm(["header"]),
    "missing_scorecard": _rm(["scorecard"]),
    "missing_reasons_audit": _rm(["reasons_audit"]),
    "missing_tips": _rm(["tips"]),
    "missing_method": _rm(["method"]),
    "missing_run_info": _rm(["run_info"]),
    "missing_diff": _rm(["scorecard", 0, "diff"]),
    "bad_version": lambda d: d.update(schema_version="9.9.9"),
    "extra_top_key": lambda d: d.update(surprise=1),
    "bad_status": lambda d: d["reasons_audit"].update(status="maybe"),
    "bad_diff_status": lambda d: d["scorecard"][0]["diff"].update(status="close"),
    "bad_kind": lambda d: d["scorecard"][0].update(kind="other"),
    "not_official_false": lambda d: d["method"].update(not_official_miti_coding=False),
    "negative_offset": lambda d: d["tips"][0]["quote"].update(start=-1),
    "bad_rank": lambda d: d["tips"][0].update(rank=0),
    "bad_warning_code": lambda d: d["warnings"].append({"code": "Not A Code"}),
    "n_runs_zero": lambda d: d["header"].update(n_runs=0),
    "string_count": lambda d: d["behaviours"][0].update(instances_total="many"),
}


@pytest.mark.parametrize("name", sorted(MUTATIONS))
def test_malformed_rejected_by_schema_and_models(validator, name):
    doc = copy.deepcopy(load("report_full.json"))
    MUTATIONS[name](doc)
    assert list(validator.iter_errors(doc)), "schema accepted a malformed report"
    with pytest.raises(ValidationError):
        Report.model_validate(doc)


def test_committed_schema_in_sync_with_models():
    """Regenerate with `python -m onolys_evaluation.report --write`."""
    assert SCHEMA_PATH.read_text() == schema_text()
    assert json.loads(SCHEMA_PATH.read_text()) == report_schema()


def test_schema_version_pinned():
    schema = json.loads(SCHEMA_PATH.read_text())
    assert SCHEMA_VERSION == "0.0.1"
    assert schema["properties"]["schema_version"]["const"] == "0.0.1"


def test_types_load_from_schema_keys():
    """The typed Report has exactly the R7 top-level keys that the schema lists."""
    schema = json.loads(SCHEMA_PATH.read_text())
    keys = set(schema["properties"])
    assert keys == set(Report.model_fields)
    assert keys == {
        "schema_version", "request_id", "created_at", "header", "layout", "scorecard", "globals",
        "behaviours", "summaries", "reasons_audit", "tips", "method", "aggregates", "warnings",
        "run_info",
    }
    assert set(schema["required"]) == keys - {"request_id"}
    assert set(schema["$defs"]["Header"]["properties"]) == {
        "change_goal", "protocol", "language", "coded_span", "subject_speaker", "n_runs",
        "models", "stt", "preset", "code_version", "params", "has_clinician_rating",
        "rating_coverage",
    }


def test_fixture_transcript_and_paudit_result_are_valid():
    t = load("transcript.json")
    Transcript.model_validate(t)
    PauditResult.model_validate(load("paudit_result.json"))
    sm = load("speaker_map.json")
    assert set(sm) == {"subject", "other"}


def _turn_texts(transcript):
    return {t["id"]: t["text"] for t in transcript["turns"]}


def _lines(doc):
    """Every {turn_id,start,end,quote|text} citation in a report."""
    out = []
    for g in doc["globals"]:
        out += g["onolys"]["evidence"] + g["explanation"]["onolys_lines"]
        out += g["explanation"]["clinician_support_lines"]
    for b in doc["behaviours"]:
        out += b["instances"] + b["explanation"]["onolys_lines"]
        out += b["explanation"]["clinician_support_lines"]
    for item in doc["reasons_audit"]["items"]:
        for c in item["claims"]:
            out += c["evidence"]
    for t in doc["tips"]:
        q = t["quote"]
        out.append({**q, "quote": q["text"]})
    return out


def test_every_report_quote_is_a_transcript_substring(report_doc, transcript):
    texts = _turn_texts(transcript)
    lines = _lines(report_doc)
    assert lines, "fixture has no quotes at all"
    for ln in lines:
        text = texts[ln["turn_id"]]
        assert text[ln["start"]:ln["end"]] == ln["quote"], ln


def test_tips_are_clinician_turns_and_at_least_three(report_doc, transcript):
    sm = load("speaker_map.json")
    by_id = {t["id"]: t for t in transcript["turns"]}
    assert len(report_doc["tips"]) >= 3
    for t in report_doc["tips"]:
        assert by_id[t["quote"]["turn_id"]]["speaker"] == sm["subject"]
    assert [t["rank"] for t in report_doc["tips"]] == list(range(1, len(report_doc["tips"]) + 1))


def test_report_fixtures_are_in_sync_with_generator():
    from _make_fixtures import build_all

    for name, doc in build_all().items():
        assert load(f"{name}.json") == doc, name


def test_run_info_entries_are_core_run_info(report_doc):
    from onolys_core.run_info import RunInfo

    ri = report_doc["run_info"]
    RunInfo.model_validate(ri["evaluation"])
    RunInfo.model_validate(ri["paudit"])
    if report_doc["reasons_audit"]["status"] == "skipped":
        assert ri["eaudit"] is None
    else:
        RunInfo.model_validate(ri["eaudit"])
