"""Scorer tests: tiny hand-computed cases for matching, coverage and per-bucket P/R/F1."""

import pytest

from eval.gold import GoldClaim, GoldEvidence
from eval.match import match_claims
from eval.score import aggregate, cost_usd, covered_turns, evaluate

REQUEST = {
    "transcript": [{"text": "a" * 10}, {"text": "b" * 10}, {"text": "c" * 10}, {"text": "d" * 10}]
}


def gold(cid, start, end, *, verdict="supported", required=(), allowed=(), evidence=(),
         role="control", bucket=None, contains=(), warnings=()):  # fmt: skip
    return GoldClaim(
        fixture="adhd-x", claim_id=cid, section_index=0, claim_text="t" * (end - start),
        start=start, end=end, role_in_fixture=role, bucket=bucket,
        priority="control" if role == "control" else "P0", verdict=verdict,
        concerns_required=list(required), concerns_allowed=list(allowed),
        explanation_contains=list(contains), evidence=list(evidence),
        expect_warnings=list(warnings), slots={}, status="approved",
    )  # fmt: skip


def ev(turn, role="supporting", ok=None, required=True):
    return GoldEvidence(turn=turn, role=role, roles_ok=ok or [role], required=required)


def pred(pid, start, end, verdict="supported", concerns=(), evidence=(), explanation="x"):
    return {
        "id": pid,
        "span": {"start": {"index": 0, "char": start}, "end": {"index": 0, "char": end}},
        "verdict": verdict,
        "explanation": explanation,
        "concerns": [{"type": c, "explanation": "e", "evidence_ids": []} for c in concerns],
        "evidence": list(evidence),
    }


def span(si, sc, ei, ec, role="supporting"):
    return {
        "id": "e", "role": role,
        "span": {"start": {"index": si, "char": sc}, "end": {"index": ei, "char": ec}},
    }  # fmt: skip


# -- matching --------------------------------------------------------------------------------


def test_exact_match_and_extra_and_missed():
    g = [gold("g1", 0, 10), gold("g2", 20, 30)]
    r = match_claims(g, [pred("c1", 0, 10), pred("c2", 50, 60)])
    assert [m.gold.claim_id for m in r.matched] == ["g1"]
    assert [c["id"] for c in r.extras] == ["c2"] and [x.claim_id for x in r.missed] == ["g2"]


def test_split_claims_take_the_worst_verdict_and_union_of_concerns():
    g = [gold("g1", 0, 20)]
    r = match_claims(g, [pred("c1", 0, 10, "supported"),
                         pred("c2", 10, 20, "contradicted", ["negation_reversal"])])  # fmt: skip
    (m,) = r.matched
    assert [p["id"] for p in m.preds] == ["c1", "c2"] and r.extras == []
    assert m.verdict == "contradicted" and m.concerns == {"negation_reversal"}


def test_merge_matches_the_better_overlap_and_misses_the_other_gold():
    g = [gold("g1", 0, 10), gold("g2", 10, 30)]
    r = match_claims(g, [pred("c1", 0, 30)])  # IoU 1/3 with g1, 2/3 with g2
    assert [m.gold.claim_id for m in r.matched] == ["g2"]
    assert [x.claim_id for x in r.missed] == ["g1"]


def test_overlap_below_half_does_not_match():
    r = match_claims([gold("g1", 0, 10)], [pred("c1", 6, 30)])  # 4 / 10
    assert r.matched == [] and len(r.extras) == 1


def test_ties_prefer_the_earlier_span():
    g = [gold("g1", 0, 10)]
    r = match_claims(g, [pred("late", 5, 15), pred("early", 0, 10)])
    assert r.matched[0].preds[0]["id"] == "early"


# -- turn coverage ---------------------------------------------------------------------------


def test_coverage_single_cross_turn_and_char_zero_end():
    L = [10, 10, 10, 10]
    assert covered_turns(span(1, 0, 1, 10)["span"], L) == {1}
    assert covered_turns(span(1, 4, 3, 5)["span"], L) == {1, 2, 3}  # middle turns count
    assert covered_turns(span(1, 4, 3, 0)["span"], L) == {1, 2}  # an end at char 0 covers nothing
    assert covered_turns(span(1, 10, 2, 5)["span"], L) == {2}  # start at the very end of turn 1
    assert covered_turns(span(2, 3, 2, 3)["span"], L) == set()


# -- per-bucket P/R/F1 -----------------------------------------------------------------------


def test_detection_counts_by_bucket_with_hand_computed_prf():
    g = [
        gold("g1", 0, 10, verdict="contradicted", required=["negation_reversal"],
             allowed=["contradictory_evidence"], role="target", bucket=5,
             evidence=[ev(1, "contradicting")]),
        gold("g2", 20, 30, verdict="partially_supported", required=["frequency_severity_inflation"],
             role="target", bucket=7, evidence=[ev(2)]),
        gold("g3", 40, 50),
    ]  # fmt: skip
    resp = {
        "claims": [
            pred("c1", 0, 10, "contradicted", ["negation_reversal", "contradictory_evidence"]),
            pred("c2", 20, 30, "supported"),  # misses its concern
            pred("c3", 40, 50, "supported", ["certainty_inflation"]),  # false alarm on a control
            pred("c4", 60, 70, "partially_supported", ["certainty_inflation"]),  # extra claim
        ],
        "warnings": [],
    }
    res = evaluate("v1", REQUEST, resp, g)
    d = {b: c.prf() for b, c in res.detection.items()}
    assert (d[5]["tp"], d[5]["fp"], d[5]["fn"]) == (1, 0, 0) and d[5]["f1"] == 1.0
    assert (d[7]["tp"], d[7]["fp"], d[7]["fn"]) == (0, 0, 1) and d[7]["recall"] == 0.0
    assert (d[6]["tp"], d[6]["fp"], d[6]["fn"]) == (0, 2, 0)  # control + extra claim
    assert d[6]["precision"] == 0.0 and d[6]["recall"] is None and d[6]["f1"] is None
    assert res.controls == [1, 1]  # the one control raised a concern


def test_f1_from_tp_fp_fn():
    from eval.score import Counts

    r = Counts(tp=3, fp=1, fn=2).prf()
    assert r["precision"] == pytest.approx(0.75) and r["recall"] == pytest.approx(0.6)
    assert r["f1"] == pytest.approx(2 * 0.75 * 0.6 / 1.35)


def test_verdict_accuracy_and_confusion():
    g = [gold("g1", 0, 10, verdict="contradicted", required=["negation_reversal"],
              role="target", bucket=5, evidence=[ev(1, "contradicting")]),
         gold("g2", 20, 30)]  # fmt: skip
    resp = {"claims": [pred("c1", 0, 10, "partially_supported", ["negation_reversal"]),
                       pred("c2", 20, 30)], "warnings": []}  # fmt: skip
    res = evaluate("v2", REQUEST, resp, g)
    assert res.verdict_by_bucket == {5: [0, 1]}
    assert res.confusion == {
        "contradicted": {"partially_supported": 1},
        "supported": {"supported": 1},
    }


def test_evidence_recall_precision_and_role_agreement():
    g = [gold("g1", 0, 10, verdict="contradicted", required=["negation_reversal"], role="target",
              bucket=5, evidence=[ev(1, "contradicting", ["contradicting", "qualifying"]),
                                  ev(2, "supporting", required=False)])]  # fmt: skip
    resp = {"claims": [pred("c1", 0, 10, "contradicted", ["negation_reversal"],
                            evidence=[span(1, 0, 1, 10, "qualifying"), span(3, 0, 3, 5)])],
            "warnings": []}  # fmt: skip
    res = evaluate("v2", REQUEST, resp, g)
    e = res.evidence
    assert (e["required"], e["covered"]) == (1, 1)  # only turn 1 is required
    assert (e["pred_turns"], e["pred_in_gold"]) == (2, 1)  # turn 3 is not in the gold
    assert (e["roles_checked"], e["roles_ok"]) == (1, 1)  # qualifying is in roles_ok


def test_gate_faithful_and_variant():
    g = [gold("g1", 0, 10), gold("g2", 20, 30)]
    clean = {"claims": [pred("c1", 0, 10), pred("c2", 20, 30)], "warnings": []}
    assert evaluate("faithful", REQUEST, clean, g).gate
    dirty = {"claims": [pred("c1", 0, 10), pred("c2", 20, 30, "supported", ["certainty_inflation"])],
             "warnings": []}  # fmt: skip
    assert not evaluate("faithful", REQUEST, dirty, g).gate
    one_missing = {"claims": [pred("c1", 0, 10)], "warnings": []}
    assert not evaluate("faithful", REQUEST, one_missing, g).gate
    t = [gold("g1", 0, 10, verdict="partially_supported", required=["frequency_severity_inflation"],
              role="target", bucket=7, contains=["inflates"], evidence=[ev(1)]), gold("g2", 20, 30)]  # fmt: skip
    ok = {"claims": [pred("c1", 0, 10, "partially_supported", ["frequency_severity_inflation"],
                          explanation="It Inflates the rate."), pred("c2", 20, 30)], "warnings": []}  # fmt: skip
    assert evaluate("v1", REQUEST, ok, t).gate
    wrong_word = {"claims": [pred("c1", 0, 10, "partially_supported",
                                  ["frequency_severity_inflation"], explanation="understates"),
                             pred("c2", 20, 30)], "warnings": []}  # fmt: skip
    res = evaluate("v1", REQUEST, wrong_word, t)
    assert not res.gate and "inflates" in res.gate_detail


def test_collateral_concerns_are_reported_not_gated():
    t = [gold("g1", 0, 10, verdict="partially_supported", required=["frequency_severity_inflation"],
              role="target", bucket=7, evidence=[ev(1)]), gold("g2", 20, 30)]  # fmt: skip
    resp = {"claims": [pred("c1", 0, 10, "partially_supported", ["frequency_severity_inflation"]),
                       pred("c2", 20, 30, "supported", ["timeframe_mismatch"])], "warnings": []}  # fmt: skip
    res = evaluate("v1", REQUEST, resp, t)
    assert res.gate and res.collateral == ["timeframe_mismatch"]


def test_expected_warnings_are_counted_per_matched_claim():
    t = [gold("g1", 0, 10, verdict="insufficient_evidence", required=["unsupported_claim"],
              role="target", bucket=1, warnings=["ambiguous_speaker"])]  # fmt: skip
    resp = {"claims": [pred("c1", 0, 10, "insufficient_evidence", ["unsupported_claim"])],
            "warnings": [{"code": "ambiguous_speaker", "claim_id": "c1", "message": "m"}]}  # fmt: skip
    assert evaluate("v4-noroles", REQUEST, resp, t).warnings_expected == [1, 1]
    resp["warnings"] = []
    assert evaluate("v4-noroles", REQUEST, resp, t).warnings_expected == [0, 1]


# -- aggregation and cost --------------------------------------------------------------------


def test_report_has_per_bucket_rows_flags_and_no_overall_score():
    g = [gold("g1", 0, 10, verdict="contradicted", required=["negation_reversal"], role="target",
              bucket=5, evidence=[ev(1, "contradicting")])]  # fmt: skip
    resp = {"claims": [pred("c1", 0, 10, "contradicted", ["negation_reversal"])], "warnings": []}
    rep = aggregate([evaluate("v2", REQUEST, resp, g)])
    row = rep["buckets"]["5"]
    assert row["concern"] == "negation_reversal" and row["n"] == 1 and row["f1"] == 1.0
    assert row["flags"] == ["indicative only (n < 5)"] and row["verdict_accuracy"] == {
        "correct": 1,
        "total": 1,
    }
    assert not {"f1", "overall", "score"} & set(rep) and rep["gate"]["v2"]["pass"]


def test_precision_flag_only_shows_at_n_ten():
    from eval.score import Counts, FixtureResult

    res = FixtureResult("x", True, "")
    res.detection[7] = Counts(tp=6, fp=6, fn=4)  # n = 10, precision 0.5
    assert "below the 0.8 precision target" in aggregate([res])["buckets"]["7"]["flags"]
    res.detection[7] = Counts(tp=3, fp=6, fn=2)  # n = 5: no precision flag
    assert aggregate([res])["buckets"]["7"]["flags"] == []


def test_cost_estimate_from_prices():
    prices = {"models": {"sonnet": {"input": 2.0, "output": 10.0}}}
    tokens = {"anthropic/claude-sonnet-5-5": {"input": 1_000_000, "output": 100_000,
                                              "cache_read": 1_000_000, "cache_write": 0}}  # fmt: skip
    assert cost_usd(tokens, prices) == pytest.approx(2.0 + 1.0 + 0.2)


def test_missing_every_gold_fault_scores_f1_zero_not_unmeasured():
    from eval.score import Counts

    r = Counts(tp=0, fp=0, fn=3).prf()
    assert r["recall"] == 0.0 and r["precision"] is None and r["f1"] == 0.0
    assert Counts(tp=0, fp=2, fn=3).prf()["f1"] == 0.0
    assert Counts(tp=0, fp=2, fn=0).prf()["f1"] is None  # no gold faults: recall is undefined


def test_report_and_compare_show_and_flag_a_zero_to_one_gain():
    from eval.compare import deltas
    from eval.score import Counts, FixtureResult

    def rep(counts):
        res = FixtureResult("x", True, "")
        res.detection[7] = counts
        return aggregate([res])

    missed, found = rep(Counts(tp=0, fp=0, fn=3)), rep(Counts(tp=3, fp=0, fn=0))
    assert missed["buckets"]["7"]["f1"] == 0.0 and found["buckets"]["7"]["f1"] == 1.0
    (row,) = deltas(missed, found)
    assert row["delta"] == 1.0 and row["flag"] is True
