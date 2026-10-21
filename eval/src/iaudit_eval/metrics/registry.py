"""Additive metric registry with per-dataset override.

A metric is `stat(pairs, spec, **params) -> Stats` (Counter or list) plus
`finalize(stats, spec, **params) -> Result`. Stats from disjoint pair sets are combined with
`combine` (sum for Counter, concat for list), so bootstrap resamples summed statistics.

Resolution: `datasets/<name>/metrics.py` `METRICS` first, then the core registry. No plugin
discovery.
"""

from __future__ import annotations

import importlib.util
import re
import sys
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .. import paths
from .pair import Result

POLICIES = ("primary_secondary", "none")
_NAME_RE = re.compile(r"[A-Za-z0-9_-]+")

Stats = Counter | list


@dataclass(frozen=True)
class Metric:
    name: str
    stat: Callable[..., Stats]
    finalize: Callable[..., Result]
    policy: str


@dataclass(frozen=True)
class Resolved:
    metric: Metric
    impl: str  # "core" or "dataset:<name>"


_CORE: dict[str, Metric] = {}


def _check_policy(policy: str) -> None:
    if policy not in POLICIES:
        raise ValueError(f"policy must be one of {POLICIES}, got {policy!r}")


def metric(name: str, *, policy: str, register: bool = True):
    """Class decorator: the class supplies `stat` and `finalize`; returns a `Metric`.

    `register=False` is for dataset `METRICS` modules (not added to the core registry).
    """
    _check_policy(policy)

    def deco(cls) -> Metric:
        m = Metric(name, cls.stat, cls.finalize, policy)
        if register:
            if name in _CORE:
                raise ValueError(f"metric {name!r} already registered")
            _CORE[name] = m
        return m

    return deco


def pairwise(
    name: str,
    fn: Callable[..., Result],
    *,
    policy: str,
    register: bool = False,
) -> Metric:
    """Wrap a non-additive `fn(pairs, **params) -> Result` (stat = list of pairs; slower)."""
    _check_policy(policy)
    m = Metric(
        name,
        lambda pairs, spec, **params: list(pairs),
        lambda stats, spec, **params: fn(stats, **params),
        policy,
    )
    if register:
        if name in _CORE:
            raise ValueError(f"metric {name!r} already registered")
        _CORE[name] = m
    return m


def combine(a: Stats, b: Stats) -> Stats:
    """Combine two stats: sum for Counter, concat for list."""
    if isinstance(a, Counter) and isinstance(b, Counter):
        return _add(a, b)  # not `a + b`: that drops non-positive counts
    if isinstance(a, list) and isinstance(b, list):
        return a + b
    raise TypeError(f"cannot combine {type(a).__name__} with {type(b).__name__}")


def _add(a: Counter, b: Counter) -> Counter:
    out = Counter(a)
    for k, v in b.items():
        out[k] += v
    return out


def _dataset_metrics(name: str, root: Path | None) -> dict[str, Metric] | None:
    if not _NAME_RE.fullmatch(name):
        raise ValueError(f"invalid dataset name {name!r}")
    root = Path(root) if root is not None else paths.datasets_dir()
    path = root / name / "metrics.py"
    if not path.is_file():
        return None
    modname = f"iaudit_eval_dataset_{name.replace('-', '_')}.metrics"
    spec = importlib.util.spec_from_file_location(modname, path)
    if spec is None or spec.loader is None:
        raise ValueError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[modname] = module
    try:
        spec.loader.exec_module(module)
    except Exception as e:
        sys.modules.pop(modname, None)
        raise ValueError(f"error importing {path} (dataset {name!r}): {e}") from e
    table = getattr(module, "METRICS", None)
    if not isinstance(table, dict):
        raise ValueError(f"{path} must define METRICS: dict[str, Metric]")
    return table


def resolve(name: str, dataset: Any, root: Path | None = None) -> Resolved:
    """Resolve registry key `name` for `dataset` (name, or object with `.meta.name`)."""
    ds = dataset if isinstance(dataset, str) else dataset.meta.name
    table = _dataset_metrics(ds, root)
    if table is not None and name in table:
        return Resolved(table[name], f"dataset:{ds}")
    if name in _CORE:
        return Resolved(_CORE[name], "core")
    raise KeyError(f"unknown metric {name!r} (core: {sorted(_CORE)})")


from . import builtins as _builtins  # noqa: E402,F401  (registers the built-in metrics)
