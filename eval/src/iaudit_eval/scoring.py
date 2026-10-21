"""Scoring step (B3 R8): a saved run becomes metrics.json + item_rows.json. Offline, idempotent.

Flow: run.json + item files + adapter gold -> project -> pairs -> policy -> per-cluster stats
-> bootstrap -> entries. Both reports are validated against their schemas before anything is
written, so an error leaves no partial file. Output is deterministic: entries follow metadata
order (metric, then all/one-way slices, then policy) and JSON is written with sorted keys, so
re-scoring differs only in ``scored.at``.

Default metric set (metadata has no ``metrics``): every built-in at every level, except those
that cannot run without configuration: ``recall_by_type`` (needs ``tag_key``/``tag``) and
``precision``/``recall``/``f1`` on a level with no ``positive`` label.

Failure counts: ``item_failed`` and ``unmapped`` are counted once per item; any other reason
(e.g. adapter-set ``unresolved``) once per failed pair. Items with no saved result are
``not_run``: not scored, not failures, and they make ``run.complete`` false.
"""

from __future__ import annotations

import json
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from . import store
from .datasets import registry as dataset_registry
from .datasets.base import Dataset, DatasetError, Item, Unmapped
from .metrics import bootstrap, policy
from .metrics.pair import Pair, default_pairs, metrics_config
from .metrics.registry import resolve
from .metrics.report import (
    ITEM_ROWS_SCHEMA_VERSION,
    METRICS_SCHEMA_VERSION,
    ItemRow,
    validate_item_rows,
    validate_metrics,
)

PRIMARY_POLICY = "failures_count_wrong"
_ITEM_REASONS = ("item_failed", "unmapped")
_NEEDS_POSITIVE = ("precision", "recall", "f1")


class ScoringError(ValueError):
    """Scoring could not run (unknown run, missing gold, bad references). No file is written."""


def _json_default(o: Any) -> Any:
    raise TypeError(f"not JSON serialisable: {type(o).__name__}")


def _display(v: Any) -> str:
    return v if isinstance(v, str) else json.dumps(v, sort_keys=True, default=str)


def _generic_row(item: Item, status: str, pairs: list[Pair]) -> ItemRow:
    item_pairs = [p for p in pairs if p.level == "item"] or (pairs if len(pairs) == 1 else [])
    if item_pairs:
        p = item_pairs[0]
        pred = None if p.pred is None else _display(p.pred)
        match = None if p.pred is None else bool(p.pred == p.gold)
        return {"item_id": item.id, "status": status, "gold": _display(p.gold), "pred": pred,
                "match": match}  # fmt: skip
    return {"item_id": item.id, "status": status, "gold": "", "pred": None, "match": None}


def _load_references(dataset: Dataset, datasets_root: Path | None) -> tuple[list, list]:
    ref = dataset.meta.references
    if not ref:
        return [], []
    from . import paths

    base = Path(datasets_root) if datasets_root is not None else paths.datasets_dir()
    path = base / dataset.meta.name / ref
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise ScoringError(f"cannot read references file {ref!r}: {type(e).__name__}") from e
    if not isinstance(raw, dict) or not isinstance(raw.get("rows"), list):
        raise ScoringError(f"references file {ref!r} must be an object with a 'rows' list")
    caveats = raw.get("caveats", [])
    if not isinstance(caveats, list):
        raise ScoringError(f"references file {ref!r}: 'caveats' must be a list")
    return raw["rows"], caveats


def _slice_groups(pairs: list[Pair], slices: tuple[str, ...], pool_all: bool):
    """Yield (slice dict, pairs): the all entry, then one-way slices in metadata key order."""
    if pool_all:
        yield {}, pairs
    for key in slices:
        vals: dict[Any, list[Pair]] = {}
        for p in pairs:
            if key in p.meta:
                vals.setdefault(p.meta[key], []).append(p)
        for v in sorted(vals, key=lambda x: (type(x).__name__, str(x))):
            yield {key: v}, vals[v]


def _entries(dataset: Dataset, cfg, all_pairs: list[Pair], datasets_root: Path | None) -> list:
    by_level: dict[str, list[Pair]] = {}
    for p in all_pairs:
        by_level.setdefault(p.level, []).append(p)
    defaulted = dataset.meta.metrics is None
    out = []
    for me in cfg.metrics:
        spec = cfg.levels[me.level]
        if defaulted and (
            me.fn == "recall_by_type" or (me.fn in _NEEDS_POSITIVE and spec.positive is None)
        ):
            continue
        try:
            res = resolve(me.fn, dataset, datasets_root)
        except (KeyError, ValueError) as e:
            raise ScoringError(f"metric {me.name!r}: {e}") from e
        m = res.metric
        policies = ("none",) if m.policy == "none" else ("primary", "secondary")
        for sl, group in _slice_groups(by_level.get(me.level, []), cfg.slices, cfg.pool_all):
            for pol in policies:
                subset = policy.apply(group, spec, pol)
                stats = bootstrap.cluster_stats(m, subset, spec, **me.params)
                c = bootstrap.ci(m, stats, spec, level=me.level, policy=pol, slice=sl,
                                 params=me.params)  # fmt: skip
                out.append({
                    "metric": me.name, "level": me.level, "policy": pol, "slice": sl,
                    "value": c.value, "n": c.n, "n_clusters": c.n_clusters,
                    "ci": list(c.ci) if c.ci else None, "ci_status": c.ci_status,
                    "impl": res.impl,
                })  # fmt: skip
    return out


def score(
    run_id: str,
    *,
    runs_root: Path | None = None,
    datasets_root: Path | None = None,
    data_root: Path | None = None,
) -> dict:
    """Score a saved run; write metrics.json and item_rows.json; return the metrics report."""
    from .engine import capture_git  # lazy: engine will import scoring for its on_finish hook

    try:
        run = store.load_run(runs_root, run_id)
    except (OSError, ValueError) as e:
        raise ScoringError(f"cannot read run {run_id!r}: {type(e).__name__}") from e
    try:
        dataset = dataset_registry.load(run["dataset"], root=datasets_root, data_root=data_root)
        by_id = {i.id: i for i in dataset.items(run["split"])}
    except (DatasetError, KeyError) as e:
        raise ScoringError(f"cannot load dataset for run {run_id!r}: {e}") from e
    cfg = metrics_config(dataset.meta)
    adapter = dataset.adapter
    pairs_hook = getattr(adapter, "pairs", None)
    row_hook = getattr(adapter, "item_row", None)
    saved = {it["item_id"]: it for it in store.iter_items(runs_root, run_id)}

    all_pairs: list[Pair] = []
    rows: list[dict] = []
    reasons: Counter = Counter({r: 0 for r in (*_ITEM_REASONS, "unresolved")})
    n_scored = n_failed = n_not_run = 0
    for item_id in run["item_ids"]:
        if item_id not in saved:
            n_not_run += 1
            continue
        item = by_id.get(item_id)
        if item is None:
            raise ScoringError(f"item {item_id!r} of run {run_id!r} not found in the dataset")
        try:
            gold = adapter.gold(item)
        except Exception as e:
            raise ScoringError(
                f"gold unavailable for item {item_id!r} ({type(e).__name__}); "
                "is the dataset data downloaded?"
            ) from e
        rec = saved[item_id]
        pred, failure = None, None
        if rec.get("status") == "failed":
            failure = "item_failed"
        else:
            try:
                pred = adapter.project(rec.get("response"), item)
            except Unmapped:
                failure = "unmapped"
        if failure in _ITEM_REASONS:
            reasons[failure] += 1
            n_failed += 1
        else:
            n_scored += 1
        pairs = (pairs_hook or default_pairs)(item, gold, pred, failure)
        for p in pairs:
            if p.failure is not None and p.failure not in _ITEM_REASONS:
                reasons[p.failure] += 1
        all_pairs.extend(pairs)
        status = {"item_failed": "failed", "unmapped": "unmapped"}.get(failure, "ok")
        if row_hook:
            row = row_hook(item, gold, pred, failure)
        else:
            row = _generic_row(item, status, pairs)
        rows.append(dict(row))
    rows.sort(key=lambda r: r["item_id"])

    ref_rows, caveats = _load_references(dataset, datasets_root)
    extra_hook = getattr(adapter, "report_extra", None)
    extra = extra_hook(run, runs_root) if extra_hook else {}
    git = capture_git()
    report = {
        "schema_version": METRICS_SCHEMA_VERSION,
        "run_id": run_id,
        "dataset": run["dataset"],
        "dataset_version": run.get("dataset_version") or "",
        "primary_policy": PRIMARY_POLICY,
        "scored": {
            "at": datetime.now(UTC).isoformat(),
            "metrics_version": METRICS_SCHEMA_VERSION,
            "git_commit": git.get("git_commit") or "unknown",
            "git_dirty": bool(git.get("git_dirty")),
        },
        "bootstrap": {"method": "cluster_percentile", "resamples": bootstrap.RESAMPLES,
                      "seed": bootstrap.SEED, "level": 0.95},  # fmt: skip
        "run": {
            "state": store.effective_state(runs_root, run_id),
            "complete": n_not_run == 0,
            "mapping_version": run.get("mapping_version"),
            "tags": run.get("tags") or {},
        },
        "dataset_extra": extra or {},
        "reference_caveats": caveats,
        "items": {"selected": len(run["item_ids"]), "scored": n_scored, "failed": n_failed,
                  "not_run": n_not_run},  # fmt: skip
        "failures": {"by_reason": dict(sorted(reasons.items()))},
        "entries": _entries(dataset, cfg, all_pairs, datasets_root),
        "references": ref_rows,
    }
    item_rows = {"schema_version": ITEM_ROWS_SCHEMA_VERSION, "run_id": run_id, "rows": rows}
    validate_metrics(report)
    validate_item_rows(item_rows)
    json.dumps(report, default=_json_default)  # fail before writing if not serialisable
    d = store.run_dir(runs_root, run_id)
    store.atomic_write_json(d / "metrics.json", report)
    store.atomic_write_json(d / "item_rows.json", item_rows)
    return report
