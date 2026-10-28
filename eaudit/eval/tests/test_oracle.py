"""The oracle echoes gold: it must score 1.0 everywhere and pass the POC gate. Each mutation must
move exactly the cells it should. This proves the harness before any LLM exists."""

import asyncio

import pytest

from eaudit.assembler import assemble
from eaudit.config import Settings
from eaudit.models import AuditRequest, Verdict
from eval.adapters import load_fixture, oracle_audit, run_oracle
from eval.score import aggregate, evaluate

NAMES = ["faithful", *[f"v{i}" for i in range(1, 9)], "v4-noroles"]
CFG = Settings()


def run_all(mutate=None):
    results = []
    for n in NAMES:
        req, gold = load_fixture(n)
        if mutate:
            audit = oracle_audit(req, gold)
            mutate(n, audit)
            resp = assemble(AuditRequest.model_validate(req), audit, CFG).response
        else:
            resp, _ = asyncio.run(run_oracle(req, gold, CFG))
        results.append(evaluate(n, req, resp, gold))
    return results, aggregate(results)


def cells(rep):
    out = {}
    for b, row in rep["buckets"].items():
        for k in ("tp", "fp", "fn", "n"):
            out[f"{b}.{k}"] = row[k]
        va = row["verdict_accuracy"]
        out[f"{b}.verdict"] = None if va is None else va["correct"]
    out["control.false_alarms"] = rep["control"]["false_alarms"]
    out["evidence.covered"] = rep["evidence"]["covered"]
    out["gate"] = tuple(sorted(f for f, g in rep["gate"].items() if not g["pass"]))
    return out


@pytest.fixture(scope="module")
def baseline():
    return run_all()


def test_oracle_scores_one_in_every_populated_bucket_and_passes_the_gate(baseline):
    results, rep = baseline
    assert all(r.gate for r in results), [r.fixture for r in results if not r.gate]
    for b, row in rep["buckets"].items():
        assert row["precision"] == row["recall"] == row["f1"] == 1.0, b
        assert row["verdict_accuracy"]["correct"] == row["verdict_accuracy"]["total"], b
    assert rep["control"]["false_alarm_rate"] == 0.0
    assert rep["evidence"]["recall"] == 1.0 and rep["evidence"]["role_ok_rate"] == 1.0
    assert rep["expected_warnings"] == {"seen": 1, "expected": 1}
    assert sorted(rep["buckets"], key=int) == ["1", "3", "4", "5", "7", "8", "9", "11", "12"]


def target(audit, n=None):
    return next(c for c in audit.claims if c.concerns or c.verdict != Verdict.supported)


def diff(before, after):
    return {k for k in before.keys() | after.keys() if before.get(k) != after.get(k)}


def test_wrong_verdict_that_survives_the_assembler_moves_verdict_and_gate(baseline):
    def wrong(n, audit):
        if n == "v2":
            t = target(audit)
            t.verdict = Verdict.partially_supported  # contradicted -> partially (concern kept)

    _, rep = run_all(wrong)
    assert diff(cells(baseline[1]), cells(rep)) == {"5.verdict", "gate"}
    assert rep["gate"]["v2"]["pass"] is False


def test_dropped_concern_moves_only_that_buckets_detection_cells(baseline):
    def drop(n, audit):
        if n == "v3":
            target(audit).concerns = []

    _, rep = run_all(drop)
    moved = diff(cells(baseline[1]), cells(rep))
    assert moved <= {"3.tp", "3.fn", "3.verdict", "gate"} and {"3.tp", "3.fn"} <= moved
    assert rep["buckets"]["3"]["recall"] == 0.0 and not rep["gate"]["v3"]["pass"]


def test_shifted_span_makes_the_gold_claim_missed(baseline):
    def shift(n, audit):
        if n == "v5":
            t = target(audit)
            t.span_hint = None
            t.segments = ["Alex reports losing attention"]  # elsewhere in the section

    _, rep = run_all(shift)
    moved = diff(cells(baseline[1]), cells(rep))
    assert {"4.tp", "4.fn", "gate"} <= moved
    assert rep["gate"]["v5"]["detail"] == "target claim not found"


def test_a_false_alarm_on_a_control_is_counted_once(baseline):
    def alarm(n, audit):
        if n == "faithful":
            from eaudit.assembler.models import ConcernDraft

            c = audit.claims[0]
            c.verdict = Verdict.partially_supported
            c.concerns = [ConcernDraft(type="certainty_inflation", explanation="x.",
                                       evidence_keys=[c.evidence[0].key])]  # fmt: skip

    _, rep = run_all(alarm)
    moved = diff(cells(baseline[1]), cells(rep))
    assert moved == {"control.false_alarms", "gate", "6.fp", "6.tp", "6.fn", "6.n"}
    assert rep["buckets"]["6"]["fp"] == 1 and rep["buckets"]["6"]["n"] == 0
    assert rep["control"]["false_alarms"] == 1
