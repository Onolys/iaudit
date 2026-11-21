"""Task 7: pack rules, counts, summaries ("code decides" after the model proposes)."""

import pytest

from paudit.hooks import Hooks
from paudit.pack import load_pack
from paudit.result import Instance
from paudit.score import apply_rules, compute_summaries, count_instances, score_run

pytestmark = pytest.mark.unit

MITI_RULES = [
    {"kind": "one_code_per_utterance"},
    {"kind": "max_per_unit", "unit": "volley", "code": "any", "n": 1},
    {"kind": "exclusive_group", "unit": "volley", "codes": ["sr", "cr"], "precedence": ["cr", "sr"]},
]


def inst(i, code, volley="v1", turn="t1", start=0, end=5):
    return Instance(id=f"i{i}", volley_id=volley, turn_id=turn, start=start, end=end,
                    quote="q", code=code, counted=True, rationale="r")


def by_id(res):
    return {x.id: x for x in res}


def test_two_gi_in_a_volley_one_counted():
    res, warns = apply_rules([inst(1, "gi", turn="t1"), inst(2, "gi", turn="t2")], MITI_RULES)
    r = by_id(res)
    assert r["i1"].counted and not r["i1"].uncounted_reason
    assert not r["i2"].counted and r["i2"].uncounted_reason == "duplicate_in_volley"
    assert warns == []


def test_same_code_in_different_volleys_both_counted():
    res, _ = apply_rules([inst(1, "gi", "v1", "t1"), inst(2, "gi", "v2", "t2")], MITI_RULES)
    assert all(x.counted for x in res)


def test_sr_and_cr_cr_counted_sr_superseded():
    res, _ = apply_rules([inst(1, "sr", turn="t1"), inst(2, "cr", turn="t2")], MITI_RULES)
    r = by_id(res)
    assert r["i2"].counted
    assert not r["i1"].counted and r["i1"].uncounted_reason == "superseded_by_cr"


def test_cr_first_then_sr_still_cr_wins():
    res, _ = apply_rules([inst(1, "cr", turn="t1"), inst(2, "sr", turn="t2")], MITI_RULES)
    r = by_id(res)
    assert r["i1"].counted and r["i2"].uncounted_reason == "superseded_by_cr"


def test_exclusive_group_without_precedence_first_in_text_order_wins():
    rules = [{"kind": "exclusive_group", "unit": "volley", "codes": ["a", "b"]}]
    res, _ = apply_rules([inst(1, "b", turn="t1"), inst(2, "a", turn="t2")], rules)
    r = by_id(res)
    assert r["i1"].counted and r["i2"].uncounted_reason == "superseded_by_b"


def test_one_code_per_utterance():
    res, _ = apply_rules([inst(1, "a"), inst(2, "b")], [{"kind": "one_code_per_utterance"}])
    r = by_id(res)
    assert r["i1"].counted
    assert not r["i2"].counted and r["i2"].uncounted_reason == "second_code_on_utterance"


def test_max_per_unit_specific_code_n2():
    rules = [{"kind": "max_per_unit", "unit": "volley", "code": "a", "n": 2}]
    res, _ = apply_rules([inst(1, "a", turn="t1"), inst(2, "a", turn="t2"), inst(3, "a", turn="t3"),
                          inst(4, "b", turn="t4")], rules)
    assert [x.counted for x in res] == [True, True, False, True]


def test_null_code_untouched_and_input_not_mutated():
    src = [inst(1, None), inst(2, "gi", turn="t2"), inst(3, "gi", turn="t3")]
    res, _ = apply_rules(src, MITI_RULES)
    assert res[0].counted and res[0].code is None
    assert all(x.counted for x in src)  # input untouched


def test_already_uncounted_keeps_reason_and_does_not_block_others():
    first = inst(1, "gi", turn="t1").model_copy(update={"counted": False, "uncounted_reason": "x"})
    res, _ = apply_rules([first, inst(2, "gi", turn="t2")], MITI_RULES)
    assert res[0].uncounted_reason == "x" and res[1].counted


def test_hook_can_downcount_only():
    def hook(instances, ctx):
        return [{"id": "i1", "uncounted_reason": "no_prior_client_speech"}]

    res, warns = apply_rules([inst(1, "cr"), inst(2, "gi", turn="t2")], MITI_RULES, validate_codes=hook)
    r = by_id(res)
    assert not r["i1"].counted and r["i1"].uncounted_reason == "no_prior_client_speech"
    assert r["i2"].counted and warns == []


def test_hook_cannot_add_relabel_or_recount():
    seen = {}

    def hook(instances, ctx):
        seen["ctx"] = ctx
        return [
            {"id": "i1", "code": "cr", "uncounted_reason": "relabel"},  # extra key: relabel -> ignored
            {"id": "nope", "uncounted_reason": "unknown id"},  # not an existing instance
            {"id": "i2", "counted": True},  # no reason: not a down-count
            {"id": "i3", "uncounted_reason": "dup"},  # already uncounted by a rule
        ]

    src = [inst(1, "sr", turn="t1"), inst(2, "gi", turn="t2"), inst(3, "gi", turn="t3")]
    res, warns = apply_rules(src, MITI_RULES, validate_codes=hook, ctx={"k": 1})
    r = by_id(res)
    assert [x.code for x in res] == ["sr", "gi", "gi"]
    assert len(res) == 3
    assert r["i1"].counted and r["i2"].counted
    assert r["i3"].uncounted_reason == "duplicate_in_volley"  # rule reason kept
    assert len(warns) == 4 and {w.code for w in warns} == {"hook_adjustment_ignored"}
    assert seen["ctx"] == {"k": 1}


def test_hook_receives_copies():
    def hook(instances, ctx):
        instances[0].counted = False
        return []

    res, _ = apply_rules([inst(1, "gi")], MITI_RULES, validate_codes=hook)
    assert res[0].counted


def test_counts_over_counted_only_with_zeros():
    res, _ = apply_rules([inst(1, "gi", turn="t1"), inst(2, "gi", turn="t2"), inst(3, "sr", "v2", "t3")],
                         MITI_RULES)
    assert count_instances(res, ["gi", "sr", "cr"]) == {"gi": 1, "sr": 1, "cr": 0}


def test_summaries_formula_label_and_div_by_zero():
    spec = [
        {"id": "pct", "label": "P", "expr": "cr/(sr+cr)", "reference": {"fair": 0.4, "good": 0.5}},
        {"id": "tot", "label": "T", "expr": "a+b"},
        {"id": "tech", "label": "G", "expr": "(g1+g2)/2", "reference": {"fair": 3, "good": 4}},
    ]
    out = compute_summaries(spec, {"cr": 1, "sr": 1, "a": 2, "b": 1}, {"g1": 5, "g2": 3})
    assert out["pct"].value == 0.5 and out["pct"].label == "good"
    assert out["pct"].reference.fair == 0.4
    assert out["tot"].value == 3 and out["tot"].label is None and out["tot"].reference is None
    assert out["tech"].value == 4 and out["tech"].label == "good"
    zero = compute_summaries(spec, {"cr": 0, "sr": 0, "a": 0, "b": 0}, {})
    assert zero["pct"].value is None and zero["pct"].label is None
    assert zero["tech"].value is None  # globals missing -> null
    assert zero["tot"].value == 0


def test_label_lower_better_and_below_fair():
    spec = [{"id": "x", "label": "X", "expr": "a", "reference": {"fair": 1, "good": 2, "direction": "higher_better"}}]
    assert compute_summaries(spec, {"a": 0}, {})["x"].label == "below_fair"
    assert compute_summaries(spec, {"a": 1}, {})["x"].label == "fair"


def test_compute_summary_hook_overrides_value_label_recomputed():
    spec = [{"id": "x", "label": "X", "expr": "a", "reference": {"fair": 1, "good": 2}},
            {"id": "y", "label": "Y", "expr": "a*2"}]

    def hook(counts, globals_, ctx):
        return {"x": 5.0, "unknown": 1.0}

    out = compute_summaries(spec, {"a": 1}, {}, compute_summary=hook)
    assert out["x"].value == 5.0 and out["x"].label == "good"
    assert out["y"].value == 2 and "unknown" not in out
    assert compute_summaries(spec, {"a": 1}, {}, compute_summary=lambda c, g, x: None)["x"].value == 1


def test_real_miti_pack_end_to_end():
    pack = load_pack("miti@4.2.1")
    src = [
        inst(1, "gi", "v1", "t1"), inst(2, "gi", "v1", "t2"),
        inst(3, "sr", "v2", "t3"), inst(4, "cr", "v2", "t4"),
        inst(5, "question", "v3", "t5"), inst(6, "sr", "v4", "t6"),
    ]
    res, counts, summaries, warns = score_run(pack, src, {"cct": 4, "sst": 4, "partnership": 3, "empathy": 4})
    r = by_id(res)
    assert r["i2"].uncounted_reason == "duplicate_in_volley"
    assert r["i3"].uncounted_reason == "superseded_by_cr"
    assert counts["gi"] == 1 and counts["cr"] == 1 and counts["sr"] == 1 and counts["question"] == 1
    assert set(counts) == {i["id"] for i in pack.items if i["kind"] == "count"}
    assert summaries["pct_cr"].value == 0.5 and summaries["pct_cr"].label == "good"
    assert summaries["technical"].value == 4 and summaries["technical"].label == "good"
    assert summaries["relational"].value == 3.5 and summaries["relational"].label == "fair"
    assert summaries["reflection_question_ratio"].value == 2.0
    assert summaries["total_mia"].value == 0 and summaries["total_mia"].label is None
    assert warns == []


def test_score_run_wires_pack_hooks_and_div_by_zero_without_globals():
    pack = load_pack("miti@4.2.1")
    called = []
    hooks = Hooks(validate_codes=lambda i, c: called.append(len(i)) or [])
    _, counts, summaries, _ = score_run(pack, [], {}, hooks)
    assert called == [0] and all(v == 0 for v in counts.values())
    assert summaries["pct_cr"].value is None and summaries["technical"].value is None
