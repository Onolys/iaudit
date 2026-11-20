"""Public API surface (SP03 R1): types and function signatures exist; bodies land in later tasks."""

import inspect

import pytest
from pydantic import ValidationError

import onolys_evaluation as ev
from onolys_evaluation import (
    EvaluationOutput,
    Issue,
    Report,
    Warning,
    build_report,
    run_evaluation,
    validate_rating,
)

pytestmark = pytest.mark.unit


def test_public_names_exported():
    for name in ("Report", "EvaluationOutput", "Issue", "Warning", "validate_rating",
                 "run_evaluation", "build_report"):
        assert name in ev.__all__


def test_signatures_match_prd():
    assert list(inspect.signature(validate_rating).parameters) == ["pack", "obj", "final"]
    assert list(inspect.signature(run_evaluation).parameters) == [
        "ctx", "pack", "transcript", "speaker_map", "params", "rating", "paudit_result",
        "progress_cb",
    ]
    assert inspect.iscoroutinefunction(run_evaluation)
    assert inspect.signature(run_evaluation).parameters["progress_cb"].default is None
    assert callable(build_report)
    assert all(p.kind is inspect.Parameter.KEYWORD_ONLY
               for p in inspect.signature(build_report).parameters.values())


def test_issue_carries_path_and_code_only():
    i = Issue(path="globals/cct/score", code="out_of_range")
    assert set(Issue.model_fields) == {"path", "code"}
    assert i.path == "globals/cct/score"


def test_warning_shape():
    w = Warning(code="tips_failed")
    assert w.item_id is None
    with pytest.raises(ValidationError):
        Warning(code="Bad Code")


def test_evaluation_output_fields():
    assert set(EvaluationOutput.model_fields) == {"report", "artifacts"}
    assert EvaluationOutput.model_fields["report"].annotation is Report
