"""Metrics and scoring (B3). Dataset-agnostic Pair/LevelSpec/Result and metadata config."""

from .pair import (
    BUILTIN_METRICS,
    DEFAULT_ITEM_LEVEL,
    ITEM_LEVEL,
    LevelSpec,
    MetricEntry,
    MetricsConfig,
    Pair,
    Result,
    default_pairs,
    metrics_config,
)

__all__ = [
    "BUILTIN_METRICS", "DEFAULT_ITEM_LEVEL", "ITEM_LEVEL", "LevelSpec", "MetricEntry",
    "MetricsConfig", "Pair", "Result", "default_pairs", "metrics_config",
]  # fmt: skip
