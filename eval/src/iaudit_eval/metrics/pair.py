"""Pair, LevelSpec, Result, default pair builder and B3 metadata config.

Clustering always uses `Item.doc_id`; the metadata `cluster_key` is only a free-text label.
"""

from __future__ import annotations

from collections.abc import Hashable, Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any

from ..datasets.base import DatasetMeta, Item

ITEM_LEVEL = "item"

# Names of the seven built-in metrics (implementations live in later tasks).
BUILTIN_METRICS: tuple[str, ...] = (
    "balanced_accuracy", "precision", "recall", "f1",
    "recall_by_type", "failure_rate", "coverage",
)  # fmt: skip


@dataclass(frozen=True)
class LevelSpec:
    """Label space of one level. `positive` is optional (needed by binary P/R/F1)."""

    labels: tuple[Hashable, ...]
    positive: Hashable | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "labels", tuple(self.labels))
        if self.positive is not None and self.positive not in self.labels:
            raise ValueError(f"positive {self.positive!r} not in labels {list(self.labels)}")

    @classmethod
    def from_dict(cls, raw: Mapping) -> LevelSpec:
        if not isinstance(raw, Mapping) or "labels" not in raw:
            raise ValueError("level spec must be an object with 'labels'")
        return cls(tuple(raw["labels"]), raw.get("positive"))


# Used when metadata declares no `levels`: one item-level binary level, positive = True.
DEFAULT_ITEM_LEVEL = LevelSpec((False, True), True)


@dataclass(frozen=True)
class Result:
    """A metric's value (None when undefined) and its own denominator `n`."""

    value: float | None
    n: int


@dataclass(frozen=True)
class Pair:
    """One gold/pred comparison. pred is None iff failure is set."""

    item_id: str
    cluster: str  # Item.doc_id
    level: str
    unit: str  # unique within (item, level); "" for item-level
    gold: Hashable
    pred: Hashable | None
    failure: str | None  # None = resolved; item_failed|unmapped|unresolved|adapter-defined
    meta: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "meta", MappingProxyType(dict(self.meta)))


def default_pairs(
    item: Item, gold: Hashable, pred: Hashable | None, failure: str | None
) -> list[Pair]:
    """Default builder: one item-level pair, empty unit. Built from gold even on failure."""
    if (pred is None) != (failure is not None):
        raise ValueError("pred must be None exactly when failure is set")
    return [Pair(item.id, item.doc_id, ITEM_LEVEL, "", gold, pred, failure, item.meta)]


@dataclass(frozen=True)
class MetricEntry:
    name: str  # shown in the report
    fn: str  # registry key
    level: str
    params: Mapping[str, Any] = field(default_factory=dict)
    slices: tuple[str, ...] | None = None  # None inherits the dataset's one-way slices


@dataclass(frozen=True)
class MetricsConfig:
    cluster_key: str  # label only
    levels: Mapping[str, LevelSpec]
    slices: tuple[str, ...]
    metrics: tuple[MetricEntry, ...]
    references: str | None
    pool_all: bool
    slice_partition: str | None = None


def metrics_config(meta: DatasetMeta) -> MetricsConfig:
    """Read B3 keys from dataset metadata, applying defaults.

    No `levels` -> {"item": DEFAULT_ITEM_LEVEL}. No `metrics` -> every built-in at every level.
    An explicit `metrics: []` is respected. An entry without `level` is allowed only when
    exactly one level exists.
    """
    levels = {k: LevelSpec.from_dict(v) for k, v in (meta.levels or {}).items()}
    if not levels:
        levels = {ITEM_LEVEL: DEFAULT_ITEM_LEVEL}
    if meta.metrics is None:
        entries = tuple(MetricEntry(n, n, lv, {}) for lv in levels for n in BUILTIN_METRICS)
    else:
        out = []
        for raw in meta.metrics:
            name = raw.get("name") or raw.get("fn")
            if not isinstance(name, str):
                raise ValueError(f"metric entry needs 'name' or 'fn': {raw!r}")
            level = raw.get("level")
            if level is None and len(levels) == 1:
                level = next(iter(levels))
            if level not in levels:
                raise ValueError(f"metric {name!r}: level {level!r} not in {list(levels)}")
            params = dict(raw.get("params") or {})
            slices = raw.get("slices")
            if slices is not None and (
                not isinstance(slices, (list, tuple))
                or any(not isinstance(key, str) or not key for key in slices)
            ):
                raise ValueError(f"metric {name!r}: slices must be a list of nonempty strings")
            out.append(MetricEntry(
                name, raw.get("fn") or name, level, params,
                None if slices is None else tuple(slices),
            ))
        entries = tuple(out)
    return MetricsConfig(
        cluster_key=meta.cluster_key,
        levels=MappingProxyType(levels),
        slices=tuple(meta.slices),
        metrics=entries,
        references=meta.references,
        pool_all=bool(meta.pool_all),
        slice_partition=meta.get("slice_partition"),
    )
