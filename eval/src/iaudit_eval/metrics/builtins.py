"""The seven built-in metrics (R2). All are additive: stats are Counters summed across clusters.

Failure policy is applied before `stat` (see `policy.apply`), never inside metrics.

Params
- `positive`: overrides `LevelSpec.positive` for precision/recall/f1/recall_by_type.
- `recall_by_type`: `tag_key` (meta key to read) and `tag` (value to select); both required.
- `failure_rate` / `coverage`: optional `reason` restricts failures to `pair.failure == reason`.

`n` is each metric's own denominator: pairs scored for balanced_accuracy, predicted positives for
precision, gold positives for recall/f1/recall_by_type, all pairs for failure_rate/coverage.
"""

from __future__ import annotations

from collections import Counter

from .pair import LevelSpec, Result
from .registry import metric


def _positive(spec: LevelSpec, params: dict):
    pos = params.get("positive", spec.positive)
    if pos is None:
        raise ValueError("metric needs a positive label (level spec 'positive' or param)")
    return pos


def _ratio(num: int, den: int) -> float | None:
    return num / den if den else None


@metric("balanced_accuracy", policy="primary_secondary")
class BalancedAccuracy:
    """Mean per-class recall over classes present in gold. n = pairs scored."""

    @staticmethod
    def stat(pairs, spec, **params) -> Counter:
        c: Counter = Counter()
        for p in pairs:
            c[("gold", p.gold)] += 1
            if p.pred == p.gold:
                c[("hit", p.gold)] += 1
        return c

    @staticmethod
    def finalize(stats, spec, **params) -> Result:
        golds = [k[1] for k, v in stats.items() if k[0] == "gold" and v > 0]
        if not golds:
            return Result(None, 0)
        rec = [stats[("hit", g)] / stats[("gold", g)] for g in golds]
        return Result(sum(rec) / len(rec), sum(stats[("gold", g)] for g in golds))


@metric("precision", policy="primary_secondary")
class Precision:
    """tp / predicted positives. n = predicted positives."""

    @staticmethod
    def stat(pairs, spec, **params) -> Counter:
        pos = _positive(spec, params)
        c: Counter = Counter()
        for p in pairs:
            if p.pred == pos:
                c["pp"] += 1
                if p.gold == pos:
                    c["tp"] += 1
        return c

    @staticmethod
    def finalize(stats, spec, **params) -> Result:
        return Result(_ratio(stats["tp"], stats["pp"]), stats["pp"])


@metric("recall", policy="primary_secondary")
class Recall:
    """tp / gold positives. n = gold positives."""

    @staticmethod
    def stat(pairs, spec, **params) -> Counter:
        pos = _positive(spec, params)
        c: Counter = Counter()
        for p in pairs:
            if p.gold == pos:
                c["gp"] += 1
                if p.pred == pos:
                    c["tp"] += 1
        return c

    @staticmethod
    def finalize(stats, spec, **params) -> Result:
        return Result(_ratio(stats["tp"], stats["gp"]), stats["gp"])


@metric("f1", policy="primary_secondary")
class F1:
    """2tp / (2tp + fp + fn). tp=0: 0.0 if gold positives exist, else None. n = gold positives."""

    @staticmethod
    def stat(pairs, spec, **params) -> Counter:
        pos = _positive(spec, params)
        c: Counter = Counter()
        for p in pairs:
            if p.gold == pos:
                c["gp"] += 1
                if p.pred == pos:
                    c["tp"] += 1
            elif p.pred == pos:
                c["fp"] += 1
        return c

    @staticmethod
    def finalize(stats, spec, **params) -> Result:
        tp, gp, fp = stats["tp"], stats["gp"], stats["fp"]
        if tp == 0:
            return Result(0.0 if gp > 0 else None, gp)
        return Result(2 * tp / (2 * tp + fp + (gp - tp)), gp)


@metric("recall_by_type", policy="primary_secondary")
class RecallByType:
    """Recall over gold-positive pairs whose `meta[tag_key] == tag`. n = those pairs."""

    @staticmethod
    def stat(pairs, spec, **params) -> Counter:
        pos = _positive(spec, params)
        if "tag" not in params or "tag_key" not in params:
            raise ValueError("recall_by_type needs params 'tag' and 'tag_key'")
        key, tag = params["tag_key"], params["tag"]
        c: Counter = Counter()
        for p in pairs:
            if p.gold == pos and key in p.meta and p.meta[key] == tag:
                c["gp"] += 1
                if p.pred == pos:
                    c["tp"] += 1
        return c

    @staticmethod
    def finalize(stats, spec, **params) -> Result:
        return Result(_ratio(stats["tp"], stats["gp"]), stats["gp"])


def _failure_stat(pairs, reason) -> Counter:
    c: Counter = Counter()
    for p in pairs:
        c["total"] += 1
        if p.failure is not None and (reason is None or p.failure == reason):
            c["failed"] += 1
    return c


@metric("failure_rate", policy="none")
class FailureRate:
    """failed / all pairs (optionally only failures with `reason`). n = all pairs."""

    @staticmethod
    def stat(pairs, spec, **params) -> Counter:
        return _failure_stat(pairs, params.get("reason"))

    @staticmethod
    def finalize(stats, spec, **params) -> Result:
        return Result(_ratio(stats["failed"], stats["total"]), stats["total"])


@metric("coverage", policy="none")
class Coverage:
    """1 - failure_rate. n = all pairs."""

    @staticmethod
    def stat(pairs, spec, **params) -> Counter:
        return _failure_stat(pairs, params.get("reason"))

    @staticmethod
    def finalize(stats, spec, **params) -> Result:
        r = _ratio(stats["failed"], stats["total"])
        return Result(None if r is None else 1 - r, stats["total"])
