"""Synchronous read projections, called in worker threads by the HTTP routes."""

from __future__ import annotations

import json

from iaudit_eval import compare as comparison
from iaudit_eval import store
from iaudit_eval.datasets.registry import dataset_folder
from iaudit_eval.metrics.report import validate_compare, validate_item_rows, validate_metrics
from iaudit_eval.server.guards import (
    ApiError,
    not_found,
    resolve_under,
    validate_dataset_id,
    validate_item_id,
    validate_run_id,
)


class RunReader:
    def __init__(self, manager):
        self.manager = manager
        self.runs_root = manager.runs_root

    def list_runs(self) -> list[dict]:
        if not self.runs_root.is_dir():
            return []
        result = []
        for path in self.runs_root.iterdir():
            try:
                validate_run_id(path.name)
                result.append(self.manager._read_summary(path.name))
            except (ApiError, OSError, ValueError, KeyError):
                # Ignore incomplete/foreign folders without logging their names.
                continue
        return sorted(result, key=lambda run: (run["created_at"], run["run_id"]), reverse=True)

    def detail(self, run_id: str) -> dict:
        summary = self.manager._read_summary(run_id)
        run = self.manager._read_run(run_id)
        progress = store.progress(self.runs_root, run_id)
        info_keys = (
            "git_commit", "git_dirty", "fingerprint", "mapping_version", "seed", "concurrency",
            "max_cost_usd", "tags", "mixed", "warnings",
        )
        return {
            **summary,
            "progress": {"done": progress["done"], "total": progress["total"],
                         "failures": progress["failed"], "cost_usd": progress["cost_usd"]},
            "run_info": {key: run[key] for key in info_keys if key in run},
            **({"error": run["error"]} if "error" in run else {}),
            **({"resume_refusal": refusal}
               if (refusal := self.manager.resume_refusals.get(run_id)) else {}),
        }

    def metrics(self, run_id: str) -> dict:
        summary = self.manager._read_summary(run_id)
        if summary["score_state"] != "done":
            raise not_found("Metrics are not available.")
        path = resolve_under(self.runs_root, run_id, "metrics.json")
        report = json.loads(path.read_text(encoding="utf-8"))
        validate_metrics(report)
        if report["run_id"] != run_id:
            raise not_found("Metrics are not available.")
        return report

    def items(self, run_id: str, *, filter: str, limit: int | None, offset: int) -> dict:
        summary = self.manager._read_summary(run_id)
        run = self.manager._read_run(run_id)
        row_path = resolve_under(self.runs_root, run_id, "item_rows.json")
        metrics_path = resolve_under(self.runs_root, run_id, "metrics.json")
        allowed = set(run["item_ids"])
        if (summary["score_state"] == "done" and row_path.is_file()
                and row_path.stat().st_mtime_ns >= metrics_path.stat().st_mtime_ns):
            document = json.loads(row_path.read_text(encoding="utf-8"))
            validate_item_rows(document)
            if document["run_id"] != run_id:
                raise not_found("Items are not available.")
            rows = [row for row in document["rows"] if row["item_id"] in allowed]
        else:
            rows = [
                {"item_id": record["item_id"], "status": record["status"],
                 "gold": None, "pred": None, "match": None}
                for record in store.iter_items(self.runs_root, run_id)
                if record["item_id"] in allowed
            ]
        rows.sort(key=lambda row: row["item_id"])
        if filter == "failed":
            rows = [row for row in rows if row["status"] == "failed"]
        elif filter == "mismatch":
            rows = [row for row in rows if row["match"] is False]
        page = rows[offset:] if limit is None else rows[offset:offset + limit]
        return {"total": len(rows), "items": page}

    def item_detail(self, run_id: str, item_id: str) -> dict:
        run = self.manager._read_run(run_id)
        validate_item_id(item_id, set(run["item_ids"]))
        path = resolve_under(self.runs_root, run_id, "items", f"{item_id}.json")
        if not path.is_file():
            raise not_found("Item not found.")
        record = json.loads(path.read_text(encoding="utf-8"))
        if record["item_id"] != item_id:
            raise not_found("Item not found.")
        resolve_under(self.manager.data_root, run["dataset"])
        dataset = self.manager._datasets.get(run["dataset"])
        if dataset is None:
            dataset = self.manager._load_dataset(run["dataset"])
        item = next((item for item in dataset.items(run["split"]) if item.id == item_id), None)
        if item is None:
            raise not_found("Item not found.")
        return {
            "item_id": item_id, "status": record["status"], "request": record["request"],
            "response": record.get("response"), "failure": record.get("failure"),
            "run_info": record.get("run_info"), "gold": dataset.adapter.gold(item),
            "gold_kind": dataset.meta.gold_kind,
        }

    def compare(self, run_a: str, run_b: str) -> dict:
        a = self.manager._read_run(run_a)
        b = self.manager._read_run(run_b)
        if a["dataset"] != b["dataset"]:
            raise ApiError("invalid_request", 422, "Runs use different datasets.")
        for run_id, run in ((run_a, a), (run_b, b)):
            self.manager._item_paths(run_id, run)
            name = validate_dataset_id(run["dataset"])
            folder = dataset_folder(name, self.manager.datasets_root)
            for filename in ("metadata.json", "adapter.py", "metrics.py"):
                resolve_under(self.manager.datasets_root, folder.parent.name, name, filename)
            resolve_under(self.manager.data_root, name)
        try:
            result = comparison.compare(
                run_a, run_b, runs_root=self.runs_root,
                datasets_root=self.manager.datasets_root, data_root=self.manager.data_root,
            )
        except comparison.CompareError as exc:
            raise ApiError("invalid_request", 422, "Runs cannot be compared.") from exc
        validate_compare(result)
        return result
