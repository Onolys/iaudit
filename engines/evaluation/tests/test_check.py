"""Task 10 / R9 / AC10-11: pass/fail logic of `python -m onolys_evaluation.check` (offline)."""

import copy
import json

import pytest
from conftest import load
from onolys_core.transcript import Transcript

from onolys_evaluation import check
from onolys_evaluation.check import PRICES_USD_PER_MTOK, estimate_cost, evaluate

pytestmark = pytest.mark.unit

STAGES = {"paudit": 30.0, "eaudit": 50.0, "tips": 12.0, "compare": 0.1, "assemble": 0.1}


@pytest.fixture
def tr():
    return Transcript.model_validate(load("transcript.json"))


@pytest.fixture
def report():
    return copy.deepcopy(load("report_full.json"))


def ev(report, tr, **kw):
    kw.setdefault("stage_s", STAGES)
    kw.setdefault("proposals", len(report["tips"]))
    kw.setdefault("wall_s", 80.0)
    return evaluate(report, tr, **kw)


def test_full_fixture_report_passes(report, tr):
    r = ev(report, tr)
    assert r.passed and r.problems == []
    assert r.tips_valid == 3 and r.reasons_status == "ran"
    assert r.quote_valid_rate == 1.0


def test_fewer_than_three_tips_fails(report, tr):
    report["tips"] = report["tips"][:2]
    r = ev(report, tr)
    assert not r.passed and any("tips" in p for p in r.problems)


def test_reasons_audit_not_ran_fails(report, tr):
    for status in ("skipped", "failed", "partial"):
        report["reasons_audit"]["status"] = status
        r = ev(report, tr)
        assert not r.passed and any("reasons_audit" in p for p in r.problems), status


def test_tip_quote_not_in_transcript_fails_and_lowers_rate(report, tr):
    report["tips"][0]["quote"]["text"] = "words nobody said"
    r = ev(report, tr)
    assert not r.passed  # 2 verifiable tips left
    assert r.tips_valid == 2 and r.quote_valid_rate == pytest.approx(2 / 3)


def test_quote_valid_rate_counts_rejected_proposals(report, tr):
    r = ev(report, tr, proposals=5)  # model proposed 5, code kept 3
    assert r.passed and r.quote_valid_rate == pytest.approx(3 / 5)


def test_no_proposals_rate_is_zero_not_a_crash(report, tr):
    report["tips"] = []
    r = ev(report, tr, proposals=0)
    assert not r.passed and r.quote_valid_rate == 0.0


def test_tokens_and_cost_come_from_run_info(report, tr):
    info = report["run_info"]
    info["paudit"]["usage"] = {"calls": 3, "input_tokens": 1_000_000, "output_tokens": 100_000,
                               "cache_read_tokens": 0, "cache_write_tokens": 0}
    info["eaudit"]["usage"] = {"calls": 10, "input_tokens": 0, "output_tokens": 0,
                               "cache_read_tokens": 1_000_000, "cache_write_tokens": 1_000_000}
    info["evaluation"]["usage"] = {"calls": 1, "input_tokens": 0, "output_tokens": 0,
                                   "cache_read_tokens": 0, "cache_write_tokens": 0}
    r = ev(report, tr)
    assert r.usage["paudit"]["input_tokens"] == 1_000_000
    assert r.total_calls == 14
    p = PRICES_USD_PER_MTOK
    want = (p["input"] + 0.1 * p["output"] + p["cache_read"] + p["cache_write"])
    assert r.cost_usd == pytest.approx(want)


def test_estimate_cost_zero_and_missing_engine():
    assert estimate_cost({"calls": 0, "input_tokens": 0, "output_tokens": 0,
                          "cache_read_tokens": 0, "cache_write_tokens": 0}) == 0.0
    assert estimate_cost({}) == 0.0


def test_eaudit_run_info_missing_is_tolerated(report, tr):
    report["run_info"]["eaudit"] = None
    r = ev(report, tr)
    assert "eaudit" not in r.usage  # nothing to count; pass/fail still decided by status


def test_format_prints_stage_latency_tokens_and_no_key(report, tr, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-secret-value")
    text = check.format_result(ev(report, tr))
    for word in ("paudit", "eaudit", "tips", "quote-valid", "tokens", "PASS", "cost"):
        assert word in text
    assert "sk-secret-value" not in text


def test_format_lists_problems_on_fail(report, tr):
    report["tips"] = []
    text = check.format_result(ev(report, tr, proposals=0))
    assert "FAIL" in text and "tips" in text


def test_stage_timer_records_started_to_done():
    clock = iter([10.0, 12.5, 11.0, 20.0])
    t = check.StageTimer(now=lambda: next(clock))
    t("paudit", "started")
    t("tips", "started")
    t("paudit", "done")
    t("tips", "done")
    assert t.stage_s == {"paudit": 1.0, "tips": 7.5}


def test_stage_timer_failed_stage_is_recorded():
    clock = iter([0.0, 1.0])
    t = check.StageTimer(now=lambda: next(clock))
    t("eaudit", "started")
    t("eaudit", "failed")
    assert t.stage_s == {"eaudit": 1.0} and t.failed == ["eaudit"]


def test_main_without_key_exits_nonzero_and_does_not_print_key(monkeypatch, capsys):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert check.main([]) == 1
    assert "ANTHROPIC_API_KEY" in capsys.readouterr().err


def test_default_pack_is_the_only_pack_dir():
    assert check.default_pack().name == "miti-4.2.1"


def test_rating_card_fixture_is_a_valid_final_card():
    from conftest import FIXTURES
    from paudit.pack import load_pack

    from onolys_evaluation import validate_rating

    card = json.loads((FIXTURES / "rating_card.json").read_text(encoding="utf-8"))
    assert validate_rating(load_pack("miti@4.2.1"), card, final=True) == []
