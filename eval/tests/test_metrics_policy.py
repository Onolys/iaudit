import json
from dataclasses import replace

import pytest

from iaudit_eval.metrics.pair import LevelSpec, Pair
from iaudit_eval.metrics.policy import FAILED, apply

BIN = LevelSpec((False, True), True)
KARY = LevelSpec(("a", "b", "c"))


def P(i, gold, pred, failure=None, level="item"):
    return Pair(f"i{i}", f"d{i}", level, "", gold, pred, failure)


def pr(pairs, labels):
    """Inline per-class (precision, recall) over labels."""
    out = {}
    for c in labels:
        tp = sum(p.gold == c and p.pred == c for p in pairs)
        pp = sum(p.pred == c for p in pairs)
        gp = sum(p.gold == c for p in pairs)
        out[c] = (tp / pp if pp else None, tp / gp if gp else None)
    return out


def test_binary_primary_failed_positive_is_miss_negative_is_false_alarm():
    pairs = [P(1, True, None, "item_failed"), P(2, False, None, "unmapped"), P(3, True, True)]
    out = apply(pairs, BIN, "primary")
    assert [p.pred for p in out] == [False, True, True]
    assert [p.failure for p in out] == ["item_failed", "unmapped", None]
    assert out[0].gold is True  # miss: gold pos, pred neg
    assert out[1].gold is False  # false alarm: gold neg, pred pos
    assert pr(out, [True])[True] == (1 / 2, 1 / 2)


def test_kary_primary_lowers_recall_not_precision():
    before = [P(1, "a", "a"), P(2, "b", "b"), P(3, "a", "a")]
    base = pr(before, KARY.labels)
    pairs = before + [P(4, "a", None, "unresolved")]
    out = apply(pairs, KARY, "primary")
    assert out[-1].pred is FAILED and out[-1].failure == "unresolved"
    after = pr(out, KARY.labels)
    assert after["a"][0] == base["a"][0] and after["b"][0] == base["b"][0]
    assert after["a"][1] < base["a"][1]
    assert FAILED not in KARY.labels
    assert all(p.pred != FAILED for p in out[:3])


def test_secondary_drops_failed():
    pairs = [P(1, True, None, "x"), P(2, True, True)]
    assert apply(pairs, BIN, "secondary") == [pairs[1]]


def test_none_untouched():
    pairs = [P(1, True, None, "x"), P(2, True, True)]
    assert apply(pairs, BIN, "none") == pairs


def test_no_none_pred_after_primary_or_secondary():
    pairs = [P(1, "a", None, "x"), P(2, "b", "b")]
    for pol in ("primary", "secondary"):
        assert all(p.pred is not None for p in apply(pairs, KARY, pol))


def test_input_not_mutated_and_pairs_replaced():
    p = P(1, True, None, "x")
    out = apply([p], BIN, "primary")
    assert p.pred is None and out[0] == replace(p, pred=False)


def test_unknown_policy():
    with pytest.raises(ValueError):
        apply([], BIN, "bogus")


def test_sentinel_stable():
    assert FAILED == FAILED and FAILED != "FAILED" and FAILED != None  # noqa: E711
    assert hash(FAILED) == hash(FAILED) and {FAILED: 1}[FAILED] == 1
    assert json.dumps(FAILED) == '"FAILED"' and str(FAILED) == "FAILED"
    assert sorted(["b", FAILED, "a"]) == [FAILED, "a", "b"]


def test_nonbinary_wrong_for_binary_gold_outside_labels():
    with pytest.raises(ValueError):
        apply([P(1, "zzz", None, "x")], BIN, "primary")
