"""Export the offline eval API contract: python -m iaudit_eval.server.export_schema."""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from pathlib import Path

from pydantic import TypeAdapter

from iaudit_eval import paths
from iaudit_eval.server import models

ROUTES = {
    "GET /health": "Health",
    "GET /datasets": "DatasetSummary[]",
    "GET /datasets/{name}": "DatasetMeta",
    "POST /datasets/{name}/download": "DownloadStatus",
    "GET /datasets/{name}/download": "DownloadStatus",
    "POST /runs/estimate": "Estimate",
    "POST /runs": "RunCreated",
    "GET /runs": "RunSummary[]",
    "GET /runs/{id}": "RunDetail",
    "POST /runs/{id}/abort": "RunSummary",
    "POST /runs/{id}/resume": "RunSummary",
    "GET /runs/{id}/metrics": "MetricsReport",
    "GET /runs/{id}/items": "ItemPage",
    "GET /runs/{id}/items/{item_id}": "ItemDetail",
    "POST /runs/{id}/rescore": "RunSummary",
    "GET /compare": "Comparison",
}
REQUESTS = {"POST /runs/estimate": "EstimateRequest", "POST /runs": "RunRequest"}
ERRORS = {str(status): "ErrorResponse" for status in (403, 404, 409, 422, 500, 502)}
_MODELS = (
    models.Health, models.DatasetSummary, models.DatasetMeta, models.DownloadStatus,
    models.EstimateRequest, models.RunRequest, models.Estimate, models.RunCreated,
    models.RunSummary, models.RunDetail, models.ItemPage, models.ItemDetail, models.ErrorResponse,
)


def schema_path() -> Path:
    return paths.repo_root() / "eval" / "api" / "eval-api.schema.json"


def build_schema() -> dict:
    definitions = {}
    for model in _MODELS:
        schema = TypeAdapter(model).json_schema(ref_template="#/$defs/{model}")
        definitions.update(schema.pop("$defs", {}))
        definitions[model.__name__] = schema
    for name, filename in (("MetricsReport", "metrics.schema.json"),
                           ("Comparison", "compare.schema.json")):
        # Keep each embedded resource's $id and local $defs intact. Its local refs
        # resolve against that resource, avoiding collisions (both define "count").
        definitions[name] = json.loads((paths.schemas_dir() / filename).read_text("utf-8"))
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "https://iaudit.local/schemas/eval-api.schema.json",
        "title": "iaudit eval HTTP API",
        "$defs": definitions,
        "x-routes": ROUTES,
        "x-requests": REQUESTS,
        "x-errors": ERRORS,
    }


def render_schema() -> str:
    return json.dumps(build_schema(), indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=schema_path())
    output = parser.parse_args(argv).output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(render_schema(), encoding="utf-8")


if __name__ == "__main__":
    main()
