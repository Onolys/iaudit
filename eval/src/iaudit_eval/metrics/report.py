"""metrics.json / item_rows.json contracts: schema validation and the common ItemRow shape.

Errors list schema paths and keyword wording only, never instance values.
"""

from __future__ import annotations

import json
from functools import cache
from pathlib import Path
from typing import Any, Literal, NotRequired, TypedDict

from jsonschema import Draft202012Validator

from ..paths import schemas_dir

METRICS_SCHEMA_VERSION = "1.0.0"
ITEM_ROWS_SCHEMA_VERSION = "1.0.0"


class ItemRow(TypedDict):
    """Common per-item row (R8). gold/pred are short display strings; detail is dataset-private."""

    item_id: str
    label: NotRequired[str]
    status: Literal["ok", "failed", "unmapped"]
    gold: str
    pred: str | None
    match: bool | None
    outcome: NotRequired[str]
    detail: NotRequired[dict[str, Any]]


class ReportSchemaError(ValueError):
    """Raised when a report or item-rows object violates its schema."""

    def __init__(self, what: str, issues: list[str]):
        self.issues = issues
        super().__init__(f"{what} failed schema validation: " + "; ".join(issues))


@cache
def _validator(name: str) -> Draft202012Validator:
    schema = json.loads(Path(schemas_dir(), name).read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema)


def _check(name: str, what: str, obj: Any) -> None:
    errors = sorted(_validator(name).iter_errors(obj), key=lambda e: list(map(str, e.path)))
    if errors:
        issues = [
            f"{'/'.join(map(str, e.path)) or '<root>'}: violates '{e.validator}'"
            for e in errors[:10]
        ]
        raise ReportSchemaError(what, issues)


def validate_metrics(obj: Any) -> None:
    _check("metrics.schema.json", "metrics report", obj)


def validate_item_rows(obj: Any) -> None:
    _check("item_rows.schema.json", "item rows", obj)
