"""PauditResult models + paudit-result.schema.json (PRD R3): validity, strictness, round trip,
and sync between the committed schema and the models."""

import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
from onolys_core.run_info import RunInfo
from pydantic import ValidationError

from paudit.result import (
    SCHEMA_VERSION,
    WARNING_CODES,
    PauditResult,
    result_schema,
    schema_text,
)

pytestmark = pytest.mark.unit

SCHEMA_PATH = Path(__file__).resolve().parents[1] / "schemas" / "paudit-result.schema.json"


def _stat(v):
    return {"mean": float(v), "min": v, "max": v, "values": [v]}


def sample() -> dict:
    inst = {
        "id": "i1", "volley_id": "v1", "turn_id": "t3", "start": 0, "end": 12,
        "start_ms": 1000, "end_ms": 2500, "quote": "Hello there.", "code": "a",
        "counted": True, "rationale": "Greeting.",
    }
    dup = {**inst, "id": "i2", "counted": False, "uncounted_reason": "duplicate_in_volley"}
    uncoded = {**inst, "id": "i3", "code": None, "start_ms": None, "end_ms": None}
    glob = {
        "score": 3, "source": "capped", "raw_score": 5, "reason": "Because.",
        "evidence": [{"turn_id": "t3", "start": 0, "end": 5, "quote": "Hello"}],
    }
    return {
        "schema_version": SCHEMA_VERSION,
        "request_id": "req-1",
        "protocol": {"id": "demo", "version": "1.0.0", "pack_hash": "ab" * 8, "pack_format": "0.0.1"},
        "language": "en",
        "change_goal": "Quit smoking",
        "coded_span": {"from_s": 0, "to_s": 600},
        "subject_speaker": "S1",
        "n_runs": 1,
        "results": [{
            "run_index": 0,
            "instances": [inst, dup, uncoded],
            "counts": {"a": 1, "b": 0},
            "globals": {"g1": glob},
            "summaries": {
                "s1": {"value": 0.5, "label": "fair", "reference": {"fair": 1.0, "good": 2.0}},
                "s2": {"value": None, "label": None, "reference": None},
            },
            "warnings": [{"code": "quote_not_found", "item_id": "a"}, {"code": "pack_defined_code"}],
        }],
        "aggregate": {
            "counts": {"a": _stat(1)},
            "globals": {"g1": _stat(3)},
            "summaries": {"s1": {"mean": 0.5, "min": 0.5, "max": 0.5, "values": [0.5]}},
            "representative_run": 0,
        },
        "warnings": [{"code": "language_not_validated", "severity": "info"}],
        "run_info": RunInfo(engine="paudit", code_version="abc").model_dump(mode="json"),
    }


@pytest.fixture(scope="module")
def validator():
    schema = json.loads(SCHEMA_PATH.read_text())
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema)


def _both_reject(validator, doc):
    assert list(validator.iter_errors(doc)), "schema accepted invalid doc"
    with pytest.raises(ValidationError):
        PauditResult.model_validate(doc)


def test_sample_valid_in_models_and_schema(validator):
    doc = sample()
    assert list(validator.iter_errors(doc)) == []
    PauditResult.model_validate(doc)


def test_round_trip(validator):
    model = PauditResult.model_validate(sample())
    dumped = json.loads(model.model_dump_json())
    assert list(validator.iter_errors(dumped)) == []
    assert PauditResult.model_validate(dumped) == model
    assert isinstance(model.run_info, RunInfo)


def test_optionals_may_be_omitted(validator):
    doc = sample()
    doc.pop("request_id")
    for i in doc["results"][0]["instances"]:
        i.pop("start_ms", None)
        i.pop("end_ms", None)
    doc["results"][0]["globals"]["g1"].update(source="model")
    assert list(validator.iter_errors(doc)) == []
    PauditResult.model_validate(doc)


@pytest.mark.parametrize("path", [
    ["schema_version"], ["protocol"], ["protocol", "pack_hash"], ["language"], ["subject_speaker"],
    ["n_runs"], ["results"], ["aggregate"], ["aggregate", "representative_run"], ["warnings"],
    ["run_info"], ["results", 0, "counts"], ["results", 0, "instances", 0, "counted"],
    ["results", 0, "instances", 0, "quote"], ["results", 0, "instances", 0, "start"],
    ["results", 0, "instances", 0, "rationale"], ["results", 0, "globals", "g1", "raw_score"],
    ["results", 0, "globals", "g1", "source"], ["results", 0, "summaries", "s1", "label"],
])
def test_missing_required_rejected(validator, path):
    doc = sample()
    node = doc
    for p in path[:-1]:
        node = node[p]
    del node[path[-1]]
    _both_reject(validator, doc)


@pytest.mark.parametrize("mutate", [
    lambda d: d["results"][0]["globals"]["g1"].update(source="guess"),
    lambda d: d["results"][0]["summaries"]["s1"].update(label="excellent"),
    lambda d: d["warnings"][0].update(severity="fatal"),
    lambda d: d.update(schema_version="9.9.9"),
    lambda d: d["results"][0]["instances"][0].update(counted="yes"),
    lambda d: d["results"][0]["instances"][0].update(start=-1),
    lambda d: d["results"][0]["counts"].update(a=1.5),
    lambda d: d["warnings"][0].update(code="Not A Code"),
    lambda d: d.update(n_runs=0),
    lambda d: d.update(results=[]),
    lambda d: d["protocol"].update(pack_format=1),
    lambda d: d.update(extra_field=1),
    lambda d: d["results"][0]["instances"][0].update(surprise=1),
])
def test_bad_values_rejected(validator, mutate):
    doc = sample()
    mutate(doc)
    _both_reject(validator, doc)


def test_end_before_start_rejected_by_model():
    doc = sample()
    doc["results"][0]["instances"][0].update(start=10, end=2)
    with pytest.raises(ValidationError):
        PauditResult.model_validate(doc)


def test_representative_run_must_exist_in_model():
    doc = sample()
    doc["aggregate"]["representative_run"] = 4
    with pytest.raises(ValidationError):
        PauditResult.model_validate(doc)


def test_uncounted_reason_requires_uncounted():
    doc = sample()
    doc["results"][0]["instances"][0]["uncounted_reason"] = "x"
    with pytest.raises(ValidationError):
        PauditResult.model_validate(doc)


def test_known_and_pack_defined_warning_codes_accepted(validator):
    for code in WARNING_CODES:
        doc = sample()
        doc["warnings"] = [{"code": code}]
        assert list(validator.iter_errors(doc)) == []
        PauditResult.model_validate(doc)
    assert {"short_session", "quote_not_found", "overlap", "insufficient_evidence", "capped",
            "span_ignored", "unknown_speaker", "language_not_validated", "run_failed"} == set(
        WARNING_CODES)


def test_run_info_shape_is_core_run_info():
    doc = sample()
    doc["run_info"]["bogus"] = 1
    with pytest.raises(ValidationError):
        PauditResult.model_validate(doc)


def test_committed_schema_in_sync_with_models():
    """The committed schema is generated from the models; regenerate with
    `python -m paudit.result --write` after changing them."""
    assert SCHEMA_PATH.read_text() == schema_text()
    assert json.loads(SCHEMA_PATH.read_text()) == result_schema()


def test_schema_version_pinned_in_schema():
    schema = json.loads(SCHEMA_PATH.read_text())
    assert schema["properties"]["schema_version"]["const"] == "0.0.1"
