"""Failure policy (R5): applied to a pair subset before any metric, never inside metrics."""

from __future__ import annotations

from collections.abc import Hashable, Iterable
from dataclasses import replace

from .pair import LevelSpec, Pair

POLICIES: tuple[str, ...] = ("primary", "secondary", "none")


class _Failed(str):
    """Out-of-set k-ary prediction for a failed pair. Serializes as "FAILED".

    Equal only to itself (never to the plain string "FAILED"), so it cannot collide with a label.
    """

    __slots__ = ()

    def __eq__(self, other: object) -> bool:
        return other is self

    def __ne__(self, other: object) -> bool:
        return other is not self

    def __hash__(self) -> int:
        return hash("iaudit_eval.metrics.policy.FAILED")

    def __repr__(self) -> str:
        return "FAILED"


FAILED = _Failed("FAILED")


def wrong(gold: Hashable, spec: LevelSpec) -> Hashable:
    """Binary: the other label. k-ary: FAILED (counts as no class's prediction)."""
    if len(spec.labels) == 2:
        if gold not in spec.labels:
            raise ValueError(f"gold {gold!r} not in labels {list(spec.labels)}")
        a, b = spec.labels
        return b if gold == a else a
    return FAILED


def apply(pairs: Iterable[Pair], spec: LevelSpec, policy: str) -> list[Pair]:
    if policy not in POLICIES:
        raise ValueError(f"unknown failure policy {policy!r}; expected one of {list(POLICIES)}")
    pairs = list(pairs)
    if policy == "none":
        return pairs
    if policy == "secondary":
        return [p for p in pairs if p.failure is None]
    return [
        replace(p, pred=wrong(p.gold, spec)) if p.failure is not None else p for p in pairs
    ]
