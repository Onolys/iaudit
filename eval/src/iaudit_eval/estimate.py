"""Rough pre-run numbers from prior runs of the same dataset (R8, D10).

Method: over ok items of prior runs of the dataset that reported a figure, take the
mean of ``figure / request_chars`` per item for input tokens, output tokens and cost,
then multiply by the selected items' request chars. A figure no prior item reported
stays ``None``. No prior ok item at all -> ``basis="none"``, all ``None``. No guessed
constants. Always ``rough=True``. Request text is read, never logged.

``request_chars`` is the length of the request's compact JSON without ``request_id``
(the engine adds that per run, so it must not skew the ratio).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from iaudit_eval import store
from iaudit_eval.datasets import Dataset, load
from iaudit_eval.datasets.base import DatasetError
from iaudit_eval.engine import Selection
from iaudit_eval.selection import select

COLD_NOTE = "No prior runs of this dataset reported usage: run a small N first (about 5 items)."
PRIOR_NOTE = "Rough estimate from prior runs of this dataset, scaled by request length."
_FIELDS = ("input_tokens", "output_tokens", "cost_usd")


@dataclass(frozen=True)
class Estimate:
    basis: str  # "prior_runs" | "none"
    n_items: int
    est_input_tokens: float | None
    est_output_tokens: float | None
    est_cost_usd: float | None
    rough: bool
    note: str


def request_chars(request: dict[str, Any]) -> int:
    body = {k: v for k, v in request.items() if k != "request_id"}
    return len(json.dumps(body, separators=(",", ":"), ensure_ascii=False, sort_keys=True))


def _num(v: Any) -> bool:
    return isinstance(v, int | float) and not isinstance(v, bool)


def _ratios(dataset_name: str, runs_root: Path | None) -> dict[str, list[float]]:
    ratios: dict[str, list[float]] = {f: [] for f in _FIELDS}
    for run in store.list_runs(runs_root):
        if run.get("dataset") != dataset_name:
            continue
        for it in store.iter_items(runs_root, run["run_id"]):
            info = it.get("run_info")
            req = it.get("request")
            if it.get("status") == "failed" or not info or not isinstance(req, dict):
                continue
            chars = request_chars(req)
            if chars <= 0:
                continue
            for f in _FIELDS:
                if _num(info.get(f)):
                    ratios[f].append(info[f] / chars)
    return ratios


def estimate(
    dataset: Dataset | str,
    selection: Selection | None = None,
    *,
    runs_root: Path | None = None,
    data_root: Path | None = None,
) -> Estimate:
    selection = selection or Selection()
    if isinstance(dataset, str):
        dataset = load(dataset, data_root=data_root)
    meta = dataset.meta
    split = selection.split or meta.default_split
    if not split:
        raise DatasetError("no split given and the dataset declares no default_split")
    items = select(dataset.items(split), selection.n, selection.seed)
    ratios = _ratios(meta.name, runs_root)
    if not any(ratios.values()):
        return Estimate("none", len(items), None, None, None, True, COLD_NOTE)
    total = sum(request_chars(dict(dataset.adapter.to_request(i))) for i in items)
    est = {f: (sum(r) / len(r) * total if r else None) for f, r in ratios.items()}
    return Estimate("prior_runs", len(items), est["input_tokens"], est["output_tokens"],
                    est["cost_usd"], True, PRIOR_NOTE)  # fmt: skip
