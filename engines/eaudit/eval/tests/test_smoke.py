import json

import pytest

from eval import smoke
from eval.smoke import Outcome, judge, load_fixtures, main, run_fixture

TEXT = "Alpha one. Beta two. Gamma three."


def claim(start, end, verdict="supported", concerns=(), explanation="", section=0):
    return {
        "id": f"c{start}",
        "span": {
            "start": {"index": section, "char": start},
            "end": {"index": section, "char": end},
        },
        "verdict": verdict,
        "explanation": explanation,
        "concerns": [{"type": c, "explanation": "x", "evidence_ids": []} for c in concerns],
        "evidence": [],
    }


def exp(**kw):
    base = {
        "fixture": "adhd-vx",
        "target_text": "Beta two.",
        "verdict": "contradicted",
        "concerns_required": ["negation_reversal"],
        "concerns_allowed": [],
        "explanation_contains": [],
    }
    return {**base, **kw}


def test_variant_passes_on_expected_verdict_and_concern():
    resp = {"claims": [claim(0, 10), claim(11, 20, "contradicted", ["negation_reversal"])]}
    out = judge(exp(), resp, [TEXT])
    assert out.passed and out.actual_verdict == "contradicted"
    assert out.actual_concerns == ["negation_reversal"]


def test_variant_fails_on_wrong_verdict_or_missing_concern():
    assert not judge(exp(), {"claims": [claim(11, 20, "supported")]}, [TEXT]).passed
    assert not judge(exp(), {"claims": [claim(11, 20, "contradicted")]}, [TEXT]).passed


def test_split_claims_use_worst_verdict_and_concern_union():
    resp = {
        "claims": [
            claim(11, 15, "supported"),
            claim(15, 20, "contradicted", ["negation_reversal"]),
        ]
    }
    out = judge(exp(), resp, [TEXT])
    assert out.passed and out.actual_verdict == "contradicted"


def test_no_overlapping_claim_fails():
    out = judge(exp(), {"claims": [claim(0, 10)]}, [TEXT])
    assert not out.passed and out.actual_verdict == "none"


def test_explanation_contains_is_checked_case_insensitively():
    resp = {"claims": [claim(11, 20, "contradicted", ["negation_reversal"], "It Inflates")]}
    assert judge(exp(explanation_contains=["inflates"]), resp, [TEXT]).passed
    assert not judge(exp(explanation_contains=["understates"]), resp, [TEXT]).passed


def test_collateral_concerns_are_reported_not_gated():
    resp = {
        "claims": [
            claim(0, 10, "supported", ["timeframe_mismatch"]),
            claim(11, 20, "contradicted", ["negation_reversal"]),
        ]
    }
    out = judge(exp(), resp, [TEXT])
    assert out.passed and out.collateral == ["timeframe_mismatch"]


def test_faithful_requires_all_supported_without_concerns():
    e = {"fixture": "adhd-faithful", "all_claims": {"verdict": "supported"}}
    assert judge(e, {"claims": [claim(0, 10), claim(11, 20)]}, [TEXT]).passed
    assert not judge(e, {"claims": [claim(0, 10, "partially_supported")]}, [TEXT]).passed
    assert not judge(e, {"claims": [claim(0, 10, "supported", ["x"])]}, [TEXT]).passed
    assert not judge(e, {"claims": []}, [TEXT]).passed


def test_load_fixtures_returns_nine_in_order():
    fx = load_fixtures()
    assert [f.name for f in fx] == ["faithful", *[f"v{i}" for i in range(1, 9)]]
    assert load_fixtures(["v3", "v1"])[0].name == "v1"
    with pytest.raises(ValueError):
        load_fixtures(["nope"])


def test_run_fixture_reports_http_error_as_fail():
    fx = load_fixtures(["v1"])[0]

    class R:
        status_code = 503

        def json(self):
            return {"error": {"code": "unavailable"}}

    out = run_fixture(fx, lambda body: R())
    assert not out.passed and "503" in out.detail


def test_inprocess_stub_pipeline_runs_and_fails_without_leaking_text(monkeypatch, capsys):
    monkeypatch.setenv("IAUDIT_PIPELINE", "stub")
    monkeypatch.setenv("IAUDIT_LLM_MODE", "stub")
    code = main(["--inprocess", "--only", "v1,faithful"])
    out = capsys.readouterr().out
    assert code == 1
    assert "FAIL" in out and "adhd-v1" in out
    assert "Alex" not in out and "meeting" not in out


def test_all_pass_exits_zero(monkeypatch, capsys):
    monkeypatch.setattr(
        smoke, "run_fixture", lambda fx, post: Outcome(fx.name, "x", "x", [], [], True)
    )
    assert main(["--inprocess", "--only", "v1"]) == 0
    assert "PASS" in capsys.readouterr().out


def test_expected_files_are_json():
    for f in load_fixtures():
        assert json.loads(f.expected_path.read_text())["fixture"] == f.request["request_id"]
