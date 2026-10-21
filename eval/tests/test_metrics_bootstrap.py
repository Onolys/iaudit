"""Clustered bootstrap CIs: determinism, independence, golden fixture, paired variant."""

from __future__ import annotations

import hashlib
import json
import random
from collections import Counter
from pathlib import Path

import pytest

from iaudit_eval.metrics.bootstrap import (
    RESAMPLES,
    SEED,
    ci,
    cluster_stats,
    entry_rng,
    paired_ci,
)
from iaudit_eval.metrics.pair import LevelSpec, Pair, Result
from iaudit_eval.metrics.registry import Metric

FIXTURE = Path(__file__).parent / "fixtures" / "bootstrap_10_clusters.json"
SPEC = LevelSpec((False, True), True)


def _stat(pairs, spec, **_):
    c = Counter()
    for p in pairs:
        if p.gold == spec.positive:
            c["pos"] += 1
            c["tp"] += p.pred == spec.positive
    return c


def _fin(stats, spec, **_):
    n = stats["pos"]
    return Result(stats["tp"] / n if n else None, n)


RECALL = Metric("recall", _stat, _fin, "primary_secondary")
ACC = Metric(
    "acc",
    lambda pairs, spec, **_: Counter(n=len(pairs), ok=sum(p.gold == p.pred for p in pairs)),
    lambda s, spec, **_: Result(s["ok"] / s["n"] if s["n"] else None, s["n"]),
    "none",
)


def _pairs(rows=None):
    rows = rows or json.loads(FIXTURE.read_text())["pairs"]
    return [
        Pair(f"i{k}", r["cluster"], "item", "", r["gold"], r["pred"], None)
        for k, r in enumerate(rows)
    ]


def _run(metric=RECALL, pairs=None, **kw):
    cs = cluster_stats(metric, pairs or _pairs(), SPEC)
    args = dict(level="item", policy="primary_secondary", slice=None)
    args.update(kw)
    return ci(metric, cs, SPEC, **args)


def test_cluster_stats_sorted_by_cluster():
    cs = cluster_stats(RECALL, list(reversed(_pairs())), SPEC)
    assert list(cs) == sorted(cs) and len(cs) == 10


def test_defaults_recorded():
    assert (RESAMPLES, SEED) == (1000, 0)


def test_rerun_identical():
    assert _run() == _run()


def test_unrelated_metric_does_not_change_ci():
    before = _run()
    _run(ACC, level="item", policy="none")
    assert _run() == before


def test_rng_depends_on_entry_and_slice_canonical():
    a = entry_rng(0, "recall", "item", "none", {"a": 1, "b": 2}).random()
    assert a == entry_rng(0, "recall", "item", "none", {"b": 2, "a": 1}).random()
    assert a != entry_rng(0, "recall", "item", "none", {"a": 1, "b": 3}).random()
    assert a != entry_rng(0, "f1", "item", "none", {"a": 1, "b": 2}).random()
    assert a != entry_rng(1, "recall", "item", "none", {"a": 1, "b": 2}).random()


def _naive_rng(metric, level, policy, slice_):
    key = f"0|{metric}|{level}|{policy}|{json.dumps(slice_, sort_keys=True)}"
    return random.Random(int.from_bytes(hashlib.sha256(key.encode()).digest(), "big"))


def _naive_ci(rows, rng, fin=None):
    """Independent: resample cluster row-lists directly, recompute recall from scratch."""
    by = {}
    for r in rows:
        by.setdefault(r["cluster"], []).append(r)
    clusters = [by[k] for k in sorted(by)]
    k = len(clusters)
    vals = []
    for _ in range(1000):
        flat = [r for i in [rng.randrange(k) for _ in range(k)] for r in clusters[i]]
        pos = [r for r in flat if r["gold"]]
        if pos:
            vals.append(sum(r["pred"] for r in pos) / len(pos))
    vals.sort()

    def q(p):
        x = p * (len(vals) - 1)
        lo = int(x)
        hi = min(lo + 1, len(vals) - 1)
        return vals[lo] + (vals[hi] - vals[lo]) * (x - lo)

    return q(0.025), q(0.975)


def test_golden_matches_checked_in_and_naive():
    rows = json.loads(FIXTURE.read_text())["pairs"]
    r = _run()
    assert r.ci_status == "ok" and r.n_clusters == 10
    lo, hi = _naive_ci(rows, _naive_rng("recall", "item", "primary_secondary", None))
    assert r.ci == pytest.approx((lo, hi), abs=1e-12)
    golden = json.loads(FIXTURE.read_text())["golden"]
    assert r.value == pytest.approx(golden["value"])
    assert r.n == golden["n"]
    assert r.ci == pytest.approx(tuple(golden["ci"]), abs=1e-12)


def test_few_clusters():
    rows = [{"cluster": f"c{i}", "gold": True, "pred": True} for i in range(4)]
    r = _run(pairs=_pairs(rows))
    assert (r.ci, r.ci_status, r.n_clusters, r.value) == (None, "few_clusters", 4, 1.0)


def test_undefined_value():
    rows = [{"cluster": f"c{i}", "gold": False, "pred": False} for i in range(8)]
    r = _run(pairs=_pairs(rows))
    assert (r.value, r.ci, r.ci_status, r.n_clusters) == (None, None, "undefined", 8)


def test_null_ci_below_90pct_defined():
    # one positive cluster of 10: a resample is defined only if it picks it (~65%)
    rows = [{"cluster": f"c{i}", "gold": i == 0, "pred": True} for i in range(10)]
    r = _run(pairs=_pairs(rows))
    assert r.value == 1.0 and r.ci is None and r.ci_status == "undefined"


def test_paired_null_ci_below_90pct_defined():
    rows = [{"cluster": f"c{i}", "gold": i == 0, "pred": True} for i in range(10)]
    cs = cluster_stats(RECALL, _pairs(rows), SPEC)
    d = paired_ci(RECALL, cs, cs, SPEC, level="item", policy="primary_secondary", slice=None)
    assert d.ci is None and d.ci_status == "undefined"


def test_paired_identical_runs_zero_delta():
    cs = cluster_stats(RECALL, _pairs(), SPEC)
    d = paired_ci(RECALL, cs, cs, SPEC, level="item", policy="primary_secondary", slice=None)
    assert d.delta == 0 and d.ci == (0.0, 0.0) and d.ci_status == "ok"


def test_paired_delta_is_b_minus_a_and_matches_naive():
    rows = json.loads(FIXTURE.read_text())["pairs"]
    rows_b = [dict(r, pred=True) if r["gold"] else dict(r) for r in rows]  # b: perfect recall
    ca = cluster_stats(RECALL, _pairs(rows), SPEC)
    cb = cluster_stats(RECALL, _pairs(rows_b), SPEC)
    kw = dict(level="item", policy="primary_secondary", slice=None)
    d = paired_ci(RECALL, ca, cb, SPEC, **kw)
    ra, rb = _run(), _run(pairs=_pairs(rows_b))
    assert d.a.value == ra.value and d.b.value == rb.value == 1.0
    assert d.delta == pytest.approx(1.0 - ra.value) and d.delta > 0
    # naive: shared indices over both runs
    rng = _naive_rng("recall", "item", "primary_secondary", None)
    names = sorted({r["cluster"] for r in rows})

    def rec(rs, idx):
        flat = [r for i in idx for r in rs if r["cluster"] == names[i]]
        pos = [r for r in flat if r["gold"]]
        return sum(r["pred"] for r in pos) / len(pos) if pos else None

    ds = []
    for _ in range(1000):
        idx = [rng.randrange(10) for _ in range(10)]
        x, y = rec(rows, idx), rec(rows_b, idx)
        if x is not None and y is not None:
            ds.append(y - x)
    ds.sort()

    def q(p):
        x = p * (len(ds) - 1)
        lo = int(x)
        hi = min(lo + 1, len(ds) - 1)
        return ds[lo] + (ds[hi] - ds[lo]) * (x - lo)

    assert d.ci == pytest.approx((q(0.025), q(0.975)), abs=1e-12)


def test_paired_few_clusters_and_undefined():
    rows = [{"cluster": f"c{i}", "gold": True, "pred": True} for i in range(3)]
    c = cluster_stats(RECALL, _pairs(rows), SPEC)
    d = paired_ci(RECALL, c, c, SPEC, level="item", policy="none", slice=None)
    assert d.ci is None and d.ci_status == "few_clusters"
    rows = [{"cluster": f"c{i}", "gold": False, "pred": False} for i in range(8)]
    c = cluster_stats(RECALL, _pairs(rows), SPEC)
    d = paired_ci(RECALL, c, c, SPEC, level="item", policy="none", slice=None)
    assert d.delta is None and d.ci_status == "undefined"
