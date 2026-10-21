"""Contract loader: validates against docs/contracts/ schemas in place (never copied).

Issues carry schema path and keyword wording only, never instance values (R3, D2).
"""

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT202012

from iaudit_eval.paths import contracts_dir

_NAMES = {
    "request": "audit-request.schema.json",
    "response": "audit-response.schema.json",
    "error": "error-response.schema.json",
}
_MAX_ISSUES = 5


class ContractError(RuntimeError):
    """Raised when the contract schemas cannot be loaded."""


@dataclass(frozen=True)
class Issue:
    """One validation problem: schema path + schema-derived wording only."""

    path: str
    message: str

    def __str__(self) -> str:
        return f"{self.path or '<root>'}: {self.message}"


@dataclass(frozen=True)
class Contracts:
    request: Draft202012Validator
    response: Draft202012Validator
    error: Draft202012Validator
    schemas: dict[str, dict[str, Any]]


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
    validators = {k: Draft202012Validator(s, registry=registry) for k, s in schemas.items()}
    return Contracts(schemas=schemas, **validators)


@lru_cache(maxsize=1)
def _cached(directory: Path) -> Contracts:
    return load_contracts(directory)


def get_contracts() -> Contracts:
    return _cached(contracts_dir())


def schema_version() -> str:
    """The contract version as declared by the request schema (const, or sole enum value)."""
    prop = get_contracts().schemas["request"]["properties"]["schema_version"]
    if "const" in prop:
        return prop["const"]
    enum = prop.get("enum", [])
    if len(enum) == 1:
        return enum[0]
    raise ContractError("schema_version not declared as a single value in the request schema")


def _message(e) -> str:
    """Keyword wording only: jsonschema's own messages embed instance values."""
    v = e.validator
    if v == "required":
        return "required property missing"
    if v == "additionalProperties":
        return "additional properties are not allowed"
    if v == "type":
        return f"must be of type {e.validator_value}"
    if v in ("enum", "const"):
        return "value is not allowed"
    if v in ("minLength", "minItems", "minimum", "maxItems", "maxLength", "maximum"):
        return f"violates {v} {e.validator_value}"
    return f"violates schema keyword '{v}'"


def _issues(validator: Draft202012Validator, obj: Any, limit: int | None) -> list[Issue]:
    out = [
        Issue("/".join(str(p) for p in e.absolute_schema_path), _message(e))
        for e in validator.iter_errors(obj)
    ]
    out.sort(key=lambda i: (i.path, i.message))
    return out if limit is None else out[:limit]


def validate_request(obj: Any, limit: int | None = _MAX_ISSUES) -> list[Issue]:
    return _issues(get_contracts().request, obj, limit)


def validate_response(obj: Any, limit: int | None = _MAX_ISSUES) -> list[Issue]:
    return _issues(get_contracts().response, obj, limit)


def validate_error(obj: Any, limit: int | None = _MAX_ISSUES) -> list[Issue]:
    return _issues(get_contracts().error, obj, limit)
