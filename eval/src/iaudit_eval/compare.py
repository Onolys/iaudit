"""Run-vs-run comparison on shared items (B3 R9). Offline, read-only, writes nothing.

Shared = item ids with a saved result (ok or failed) in both runs. Both runs are re-scored on
the shared set through the scoring path (not from stored metrics.json). Each delta is
``b - a`` with a paired cluster bootstrap CI (null under the R6 rules).

Disagreements compare the effective prediction after the primary failure policy; a failed pair
is displayed as ``"FAILED"`` (but it still differs only if its effective prediction differs).
Pairs are matched by (level, unit); a pair missing on one side shows ``null`` there.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from . import store
from .metrics import bootstrap, policy
from .metrics.pair import metrics_config
from .metrics.report import COMPARE_SCHEMA_VERSION, validate_compare
from .scoring import ScoringError, _collect, _display, _groups, _load_run


class CompareError(ValueError):
    """The runs cannot be compared (unknown run, different datasets, scoring failure)."""


def _skey(e_level: str, name: str, pol: str, sl: Any) -> tuple:
    return (name, e_level, pol, json.dumps(sl, sort_keys=True, default=str))


def _show(v: Any) -> str:
    return "FAILED" if v is policy.FAILED else _display(v)


def _saved(runs_root, run_id):
    try:
        return {it["item_id"]: it for it in store.iter_items(runs_root, run_id)}
    except (OSError, ValueError) as e:
        raise CompareError(f"cannot read items of run {run_id!r}: {type(e).__name__}") from e


def _effective(pairs, cfg):
    """{(item, level, unit): (effective pred, failed?)} after the primary policy."""
    out = {}
    for p in pairs:
        q = policy.apply([p], cfg.levels[p.level], "primary")[0]
        out[(p.item_id, p.level, p.unit)] = (q.pred, p.failure is not None, p)
    return out


def compare(
    run_a: str,
    run_b: str,
    *,
    runs_root: Path | None = None,
    datasets_root: Path | None = None,
    data_root: Path | None = None,
) -> dict:
    try:
        ra, ds_a, by_a = _load_run(run_a, runs_root, datasets_root, data_root)
        rb, ds_b, by_b = _load_run(run_b, runs_root, datasets_root, data_root)
    except ScoringError as e:
        raise CompareError(str(e)) from e
    if ra["dataset"] != rb["dataset"]:
        raise CompareError(f"runs use different datasets: {ra['dataset']!r} vs {rb['dataset']!r}")
    warnings = []
    for key in ("dataset_version", "mapping_version"):
        va, vb = ra.get(key), rb.get(key)
        if va != vb:
            warnings.append(f"{key} differs: {va!r} vs {vb!r}")

    sa, sb = _saved(runs_root, run_a), _saved(runs_root, run_b)
    shared = sorted(set(sa) & set(sb))
    base = {
        "schema_version": COMPARE_SCHEMA_VERSION, "run_a": run_a, "run_b": run_b,
        "dataset": ra["dataset"], "warnings": warnings, "n_shared": len(shared),
        "n_a_only": len(set(sa) - set(sb)), "n_b_only": len(set(sb) - set(sa)),
        "n_clusters_shared": 0, "deltas": [], "disagreements": [],
    }  # fmt: skip
    if not shared:
        validate_compare(base)
        return base

    try:
        ca = _collect(run_a, ds_a, by_a, sa, shared)
        cb = _collect(run_b, ds_b, by_b, sb, shared)
    except ScoringError as e:
        raise CompareError(str(e)) from e
    cfg = metrics_config(ds_a.meta)
    base["n_clusters_shared"] = len({by_a[i].doc_id for i in shared})

    try:
        groups_b = {
            _skey(me.level, me.name, pol, sl): subset
            for me, _res, _spec, sl, pol, subset in _groups(ds_b, cfg, cb.pairs, datasets_root)
        }
        deltas = []
        for me, res, spec, sl, pol, subset_a in _groups(ds_a, cfg, ca.pairs, datasets_root):
            subset_b = groups_b.get(_skey(me.level, me.name, pol, sl))
            if subset_b is None:
                continue
            m = res.metric
            st_a = bootstrap.cluster_stats(m, subset_a, spec, **me.params)
            st_b = bootstrap.cluster_stats(m, subset_b, spec, **me.params)
            kw = {"level": me.level, "policy": pol, "slice": sl, "params": me.params}
            side_a = bootstrap.ci(m, st_a, spec, **kw)
            side_b = bootstrap.ci(m, st_b, spec, **kw)
            pc = bootstrap.paired_ci(m, st_a, st_b, spec, **kw)
            deltas.append({
                "metric": me.name, "level": me.level, "policy": pol, "slice": sl,
                "a": {"value": side_a.value, "n": side_a.n,
                      "ci": list(side_a.ci) if side_a.ci else None},
                "b": {"value": side_b.value, "n": side_b.n,
                      "ci": list(side_b.ci) if side_b.ci else None},
                "delta": pc.delta,
                "delta_ci": list(pc.ci) if pc.ci else None,
                "ci_status": pc.ci_status,
                "n_clusters": pc.n_clusters,
            })  # fmt: skip
    except ScoringError as e:
        raise CompareError(str(e)) from e
    base["deltas"] = deltas

    ea, eb = _effective(ca.pairs, cfg), _effective(cb.pairs, cfg)
    by_item: dict[str, list] = {}
    for key in sorted(set(ea) | set(eb)):
        xa, xb = ea.get(key), eb.get(key)
        if xa is not None and xb is not None and xa[0] == xb[0]:
            continue
        ref = (xa or xb)[2]
        disp = lambda x: None if x is None else ("FAILED" if x[1] else _show(x[0]))  # noqa: E731
        by_item.setdefault(key[0], []).append({
            "level": key[1], "unit": key[2], "gold": _show(ref.gold),
            "a": disp(xa), "b": disp(xb),
        })  # fmt: skip
    base["disagreements"] = [
        {"item_id": i, "cluster": by_a[i].doc_id, "pairs": ps} for i, ps in by_item.items()
    ]
    validate_compare(base)
    return base
