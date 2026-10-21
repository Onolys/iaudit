"""Clustered percentile bootstrap CIs over precomputed per-cluster stats (stdlib only).

Each resample draws `k` clusters with replacement, sums their stats, and calls `finalize`.
Per-entry RNG is seeded from a hash of (seed, metric, level, policy, slice), so values do not
depend on entry order or on other metrics. Percentiles are 2.5/97.5 with linear interpolation.

Paired variant: the same resampled cluster indices apply to both runs; delta = b - a.
"""

from __future__ import annotations

import hashlib
import json
import random
from collections import Counter
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from .pair import LevelSpec, Pair, Result
from .registry import Metric, Stats

RESAMPLES = 1000
SEED = 0
MIN_CLUSTERS = 5
MIN_DEFINED = 0.9
LOW, HIGH = 0.025, 0.975

Interval = tuple[float, float]


@dataclass(frozen=True)
class CI:
    value: float | None
    n: int
    n_clusters: int
    ci: Interval | None
    ci_status: str  # ok | few_clusters | undefined


@dataclass(frozen=True)
class PairedCI:
    a: Result
    b: Result
    delta: float | None  # b - a
    n_clusters: int
    ci: Interval | None
    ci_status: str


def cluster_stats(
    metric: Metric, pairs: Iterable[Pair], spec: LevelSpec, **params: Any
) -> dict[str, Stats]:
    """Per-cluster stats, keyed by `pair.cluster` in sorted order."""
    groups: dict[str, list[Pair]] = {}
    for p in pairs:
        groups.setdefault(p.cluster, []).append(p)
    return {c: metric.stat(groups[c], spec, **params) for c in sorted(groups)}


def entry_rng(seed: int, metric: str, level: str, policy: str, slice: Any) -> random.Random:
    sl = json.dumps(slice, sort_keys=True, default=str)
    key = f"{seed}|{metric}|{level}|{policy}|{sl}"
    return random.Random(int.from_bytes(hashlib.sha256(key.encode()).digest(), "big"))


def _sum(stats: Iterable[Stats]) -> Stats:
    stats = list(stats)
    if stats and isinstance(stats[0], list):
        out: Stats = []
        for s in stats:
            out.extend(s)
        return out
    out = Counter()
    for s in stats:
        for k, v in s.items():
            out[k] += v
    return out


def _percentile(sorted_vals: list[float], q: float) -> float:
    x = q * (len(sorted_vals) - 1)
    lo = int(x)
    hi = min(lo + 1, len(sorted_vals) - 1)
    return sorted_vals[lo] + (sorted_vals[hi] - sorted_vals[lo]) * (x - lo)


def _interval(samples: list[float], resamples: int) -> Interval | None:
    if not samples or len(samples) < MIN_DEFINED * resamples:
        return None
    samples.sort()
    return (_percentile(samples, LOW), _percentile(samples, HIGH))


def ci(
    metric: Metric,
    stats: Mapping[str, Stats],
    spec: LevelSpec,
    *,
    level: str,
    policy: str,
    slice: Any = None,
    params: Mapping[str, Any] | None = None,
    seed: int = SEED,
    resamples: int = RESAMPLES,
) -> CI:
    """Value on all clusters plus a percentile bootstrap CI over clusters."""
    params = dict(params or {})
    cs = [stats[c] for c in sorted(stats)]
    k = len(cs)
    full = metric.finalize(_sum(cs), spec, **params) if k else Result(None, 0)
    if full.value is None:
        return CI(None, full.n, k, None, "undefined")
    if k < MIN_CLUSTERS:
        return CI(full.value, full.n, k, None, "few_clusters")
    rng = entry_rng(seed, metric.name, level, policy, slice)
    samples: list[float] = []
    for _ in range(resamples):
        idx = [rng.randrange(k) for _ in range(k)]
        v = metric.finalize(_sum(cs[i] for i in idx), spec, **params).value
        if v is not None:
            samples.append(v)
    return CI(full.value, full.n, k, _interval(samples, resamples), "ok")


def _empty(like: Stats) -> Stats:
    return [] if isinstance(like, list) else Counter()


def paired_ci(
    metric: Metric,
    stats_a: Mapping[str, Stats],
    stats_b: Mapping[str, Stats],
    spec: LevelSpec,
    *,
    level: str,
    policy: str,
    slice: Any = None,
    params: Mapping[str, Any] | None = None,
    seed: int = SEED,
    resamples: int = RESAMPLES,
) -> PairedCI:
    """Paired cluster bootstrap of delta = b - a over the union of clusters.

    A cluster missing from one run contributes empty stats there. Resamples where either
    value is undefined are skipped.
    """
    params = dict(params or {})
    names = sorted(set(stats_a) | set(stats_b))
    sample = next(iter([*stats_a.values(), *stats_b.values()]), Counter())
    ca = [stats_a.get(c, _empty(sample)) for c in names]
    cb = [stats_b.get(c, _empty(sample)) for c in names]
    k = len(names)
    ra = metric.finalize(_sum(ca), spec, **params) if k else Result(None, 0)
    rb = metric.finalize(_sum(cb), spec, **params) if k else Result(None, 0)
    if ra.value is None or rb.value is None:
        return PairedCI(ra, rb, None, k, None, "undefined")
    delta = rb.value - ra.value
    if k < MIN_CLUSTERS:
        return PairedCI(ra, rb, delta, k, None, "few_clusters")
    rng = entry_rng(seed, metric.name, level, policy, slice)
    samples: list[float] = []
    for _ in range(resamples):
        idx = [rng.randrange(k) for _ in range(k)]
        va = metric.finalize(_sum(ca[i] for i in idx), spec, **params).value
        vb = metric.finalize(_sum(cb[i] for i in idx), spec, **params).value
        if va is not None and vb is not None:
            samples.append(vb - va)
    return PairedCI(ra, rb, delta, k, _interval(samples, resamples), "ok")
