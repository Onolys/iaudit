from collections import Counter

import pytest

from iaudit_eval.metrics import policy
from iaudit_eval.metrics.pair import LevelSpec, Pair
from iaudit_eval.metrics.registry import combine, resolve

BIN = LevelSpec((False, True), True)
KARY = LevelSpec(("a", "b", "c"))


def P(cl, gold, pred, failure=None, **meta):
    return Pair(f"{cl}-{gold}-{pred}", cl, "item", "", gold, pred, failure, meta)


def run(name, pairs, spec, pol, **params):
    m = resolve(name, "no_such_dataset").metric
    if pol:
        pairs = policy.apply(pairs, spec, pol)
    return m.finalize(m.stat(pairs, spec, **params), spec, **params)


# Binary, 3 clusters. (gold, pred) per pair:
#  c1: (T,T) (T,F) (F,F)
#  c2: (T,T) (F,T) (T,FAIL:item_failed)
#  c3: (F,F) (F,FAIL:unmapped) (T,T)
BINARY = [
    P("c1", True, True, kind="x"), P("c1", True, False, kind="y"), P("c1", False, False),
    P("c2", True, True, kind="x"), P("c2", False, True),
    P("c2", True, None, "item_failed", kind="x"),
    P("c3", False, False), P("c3", False, None, "unmapped"), P("c3", True, True, kind="y"),
]  # fmt: skip


def test_binary_primary():
    # primary: failed gold-T -> pred F ; failed gold-F -> pred T
    # gold T: c1 2, c2 2, c3 1 = 5 ; tp = 1+1+1 = 3 -> recall 3/5
    r = run("recall", BINARY, BIN, "primary")
    assert (r.value, r.n) == (3 / 5, 5)
    # pred T = (T,T)c1,(T,T)c2,(F,T)c2,(F,T)c3-failed,(T,T)c3 = 5 ; tp 3 -> precision 3/5
    r = run("precision", BINARY, BIN, "primary")
    assert (r.value, r.n) == (3 / 5, 5)
    # fp=2 fn=2 -> f1 = 6/(6+2+2) = 0.6
    r = run("f1", BINARY, BIN, "primary")
    assert (r.value, r.n) == (pytest.approx(0.6), 5)
    # gold F = 4: hits (F,F)c1, (F,F)c3 =2 ; recall_F 2/4 ; recall_T 3/5 ; bacc = (0.5+0.6)/2
    r = run("balanced_accuracy", BINARY, BIN, "primary")
    assert (r.value, r.n) == (pytest.approx(0.55), 9)


def test_binary_secondary():
    # drop 2 failed: gold T = 4 (tp 3) ; pred T = 4 (tp 3) ; gold F = 3 (hits 2)
    r = run("recall", BINARY, BIN, "secondary")
    assert (r.value, r.n) == (3 / 4, 4)
    r = run("precision", BINARY, BIN, "secondary")
    assert (r.value, r.n) == (3 / 4, 4)
    # fp=1 fn=1 -> 6/8
    assert run("f1", BINARY, BIN, "secondary").value == pytest.approx(0.75)
    # (3/4 + 2/3)/2 = 17/24 ; n = 7
    r = run("balanced_accuracy", BINARY, BIN, "secondary")
    assert (r.value, r.n) == (pytest.approx(17 / 24), 7)


def test_failure_metrics_use_all_pairs():
    # 2 failures of 9
    r = run("failure_rate", BINARY, BIN, None)
    assert (r.value, r.n) == (2 / 9, 9)
    r = run("coverage", BINARY, BIN, None)
    assert (r.value, r.n) == (pytest.approx(7 / 9), 9)
    r = run("failure_rate", BINARY, BIN, None, reason="unmapped")
    assert (r.value, r.n) == (1 / 9, 9)
    r = run("coverage", BINARY, BIN, None, reason="unmapped")
    assert r.value == pytest.approx(8 / 9)


def test_policy_declarations():
    assert resolve("failure_rate", "x").metric.policy == "none"
    assert resolve("coverage", "x").metric.policy == "none"
    assert resolve("recall", "x").metric.policy == "primary_secondary"


def test_recall_by_type():
    # tag kind=x, gold positive: c1 (T,T), c2 (T,T), c2 (T,FAIL)
    # primary: 2/3 ; secondary: 2/2
    kw = dict(tag_key="kind", tag="x")
    r = run("recall_by_type", BINARY, BIN, "primary", **kw)
    assert (r.value, r.n) == (2 / 3, 3)
    r = run("recall_by_type", BINARY, BIN, "secondary", **kw)
    assert (r.value, r.n) == (1.0, 2)
    # kind=y: (T,F) c1, (T,T) c3 -> 1/2
    r = run("recall_by_type", BINARY, BIN, "primary", tag_key="kind", tag="y")
    assert (r.value, r.n) == (0.5, 2)
    r = run("recall_by_type", BINARY, BIN, "primary", tag_key="kind", tag="zzz")
    assert (r.value, r.n) == (None, 0)
    with pytest.raises(ValueError):
        run("recall_by_type", BINARY, BIN, "primary", tag="x")


# 3-class, 3 clusters. (gold, pred):
#  c1: (a,a) (a,b) (b,b)
#  c2: (b,c) (c,c) (c,FAIL)
#  c3: (a,a) (b,b) (c,a)
KARY_PAIRS = [
    P("c1", "a", "a"), P("c1", "a", "b"), P("c1", "b", "b"),
    P("c2", "b", "c"), P("c2", "c", "c"), P("c2", "c", None, "item_failed"),
    P("c3", "a", "a"), P("c3", "b", "b"), P("c3", "c", "a"),
]  # fmt: skip


def test_kary_balanced_accuracy():
    # primary: failed c -> FAILED (miss). a: gold 3 hits 2 ; b: gold 3 hits 2 ; c: gold 3 hits 1
    # bacc = (2/3 + 2/3 + 1/3)/3 = 5/9 ; n = 9
    r = run("balanced_accuracy", KARY_PAIRS, KARY, "primary")
    assert (r.value, r.n) == (pytest.approx(5 / 9), 9)
    # secondary: c gold 2 hits 1 -> (2/3 + 2/3 + 1/2)/3 = 11/18 ; n = 8
    r = run("balanced_accuracy", KARY_PAIRS, KARY, "secondary")
    assert (r.value, r.n) == (pytest.approx(11 / 18), 8)


def test_kary_with_positive_param():
    # positive=a: gold a 3 (tp 2) -> recall 2/3 ; pred a = 3 (a,a)(a,a)(c,a) -> precision 2/3
    r = run("recall", KARY_PAIRS, KARY, "primary", positive="a")
    assert (r.value, r.n) == (2 / 3, 3)
    r = run("precision", KARY_PAIRS, KARY, "primary", positive="a")
    assert (r.value, r.n) == (2 / 3, 3)
    with pytest.raises(ValueError):
        run("recall", KARY_PAIRS, KARY, "primary")  # no positive


def test_classes_absent_from_gold_ignored():
    pairs = [P("c1", "a", "a"), P("c1", "a", "b")]
    assert run("balanced_accuracy", pairs, KARY, "primary").value == 0.5


def test_undefined_and_f1_zero():
    only_neg = [P("c1", False, False)]
    r = run("recall", only_neg, BIN, "primary")
    assert (r.value, r.n) == (None, 0)
    r = run("precision", only_neg, BIN, "primary")
    assert (r.value, r.n) == (None, 0)
    assert run("f1", only_neg, BIN, "primary").value is None
    # gold positive exists, tp=0 -> 0.0 (even with fp)
    miss = [P("c1", True, False), P("c1", False, True)]
    assert run("f1", miss, BIN, "primary").value == 0.0
    assert run("failure_rate", [], BIN, None).value is None
    assert run("balanced_accuracy", [], BIN, "primary").value is None


def test_all_stats_additive_across_clusters():
    for name in ("balanced_accuracy", "precision", "recall", "f1", "failure_rate", "coverage"):
        m = resolve(name, "x").metric
        pol = "primary" if m.policy == "primary_secondary" else None
        pairs = policy.apply(BINARY, BIN, pol) if pol else BINARY
        whole = m.finalize(m.stat(pairs, BIN), BIN)
        parts = None
        for cl in ("c1", "c2", "c3"):
            s = m.stat([p for p in pairs if p.cluster == cl], BIN)
            assert isinstance(s, Counter)
            parts = s if parts is None else combine(parts, s)
        assert m.finalize(parts, BIN) == whole, name


@pytest.mark.parametrize("spec, gold", [(BIN, False), (BIN, True), (KARY, "a")])
def test_balanced_accuracy_require_all_declared_classes_is_opt_in(spec, gold):
    pairs = [P("c1", gold, gold)]
    default = run("balanced_accuracy", pairs, spec, "primary")
    assert (default.value, default.n) == (1.0, 1)
    required = run("balanced_accuracy", pairs, spec, "primary", require_all_classes=True)
    assert (required.value, required.n) == (None, 1)
