"""Contract loader: the JSON schemas in docs/contracts/ are the single validator."""

import json
import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal, get_args

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT202012

_NAMES = {
    "request": "audit-request.schema.json",
    "response": "audit-response.schema.json",
    "error": "error-response.schema.json",
}
_MAX_ISSUES = 5

SchemaVersion = Literal["0.0.1"]
SCHEMA_VERSION = get_args(SchemaVersion)[0]


class ContractError(RuntimeError):
    """Raised at startup when the contract schemas cannot be loaded."""


@dataclass(frozen=True)
class Issue:
    """One validation problem. Holds a schema path and schema message only, never values."""

    path: str
    message: str

    def __str__(self) -> str:
        return f"{self.path or '<root>'}: {self.message}"


def default_contracts_dir() -> Path:
    env = os.environ.get("IAUDIT_CONTRACTS_DIR")
    if env:
        return Path(env)
    # eaudit/src/eaudit/contract.py -> repo root is parents[3]
    return Path(__file__).resolve().parents[3] / "docs" / "contracts"


@dataclass(frozen=True)
class Contracts:
    request: Draft202012Validator
    response: Draft202012Validator
    error: Draft202012Validator


def load_contracts(directory: Path) -> Contracts:
    directory = Path(directory)
    if not directory.is_dir():
        raise ContractError(f"contracts directory not found: {directory}")
    schemas: dict[str, dict[str, Any]] = {}
    for key, fname in _NAMES.items():
        path = directory / fname
        if not path.is_file():
            raise ContractError(f"contract schema missing: {path}")
        try:
            schemas[key] = json.loads(path.read_text(encoding="utf-8"))
            Draft202012Validator.check_schema(schemas[key])
        except (ValueError, SchemaError) as exc:
            raise ContractError(f"contract schema invalid: {path} ({type(exc).__name__})") from exc
    registry: Registry = Registry()
    for schema in schemas.values():
        resource = Resource.from_contents(schema, default_specification=DRAFT202012)
        registry = registry.with_resource(schema.get("$id", ""), resource)
    return Contracts(**{k: Draft202012Validator(s, registry=registry) for k, s in schemas.items()})


@lru_cache(maxsize=1)
def get_contracts() -> Contracts:
    return load_contracts(default_contracts_dir())


def _issues(validator: Draft202012Validator, obj: Any, limit: int | None) -> list[Issue]:
    errors = sorted(validator.iter_errors(obj), key=lambda e: [str(p) for p in e.absolute_path])
    out = [Issue("/".join(str(p) for p in e.absolute_path), _safe_message(e)) for e in errors]
    return out if limit is None else out[:limit]


def _safe_message(e) -> str:
    """Schema-derived wording only: jsonschema's own messages embed instance values."""
    v = e.validator
    if v == "required":
        return "required property missing"
    if v == "additionalProperties":
        return "additional properties are not allowed"
    if v == "type":
        return f"must be of type {e.validator_value}"
    if v in ("enum", "const"):
        return "value is not allowed"
    if v in ("minLength", "minItems", "minimum", "maxItems"):
        return f"violates {v} {e.validator_value}"
    return f"violates schema keyword '{v}'"


def validate_request(raw: Any, limit: int | None = _MAX_ISSUES) -> list[Issue]:
    return _issues(get_contracts().request, raw, limit)


def validate_response(obj: Any, limit: int | None = _MAX_ISSUES) -> list[Issue]:
    return _issues(get_contracts().response, obj, limit)


def validate_error(obj: Any, limit: int | None = _MAX_ISSUES) -> list[Issue]:
    return _issues(get_contracts().error, obj, limit)
