"""Frozen concern agreement rules; predictions never expand the allowed sets.

On the first mapping/projection version bump, preserve the old JSON bytes as
``mapping_history/<mapping_version>.json`` before replacing ``mapping.json``.
The history directory is deliberately absent until that first bump.
"""

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from types import MappingProxyType

from jsonschema import Draft202012Validator, ValidationError

from iaudit_eval import contracts

_DATASETS = ("mediasum", "meetingbank")
# CSV gold uses this spelling; keep normalization outside the frozen JSON.
_TYPE_ALIASES = {"Tense/Modality Error": "Tense/Modality"}
_SEMVER = (
    r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)"
    r"(?:-(?:0|[1-9][0-9]*|[0-9]*[A-Za-z-][0-9A-Za-z-]*)"
    r"(?:\.(?:0|[1-9][0-9]*|[0-9]*[A-Za-z-][0-9A-Za-z-]*))*)?"
    r"(?:\+[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?\Z"
)


def normalize_type(error_type: str) -> str:
    """Return the frozen type name for a released CSV spelling."""
    return _TYPE_ALIASES.get(error_type, error_type)


@dataclass(frozen=True)
class _Rule:
    allowed: frozenset[str] | None
    datasets: frozenset[str]
    overrides: Mapping[str, frozenset[str]]


@dataclass(frozen=True)
class FrozenMapping:
    mapping_version: str
    sha256: str
    _rules: Mapping[str, _Rule]
    mapped_concerns: frozenset[str]

    def is_known_type(self, error_type: str) -> bool:
        return normalize_type(error_type) in self._rules

    def applicable_allowed(self, error_type: str, dataset: str) -> frozenset[str] | None:
        """None means recall-only or no concern agreement for this dataset."""
        if dataset not in _DATASETS:
            raise ValueError(f"Unknown TofuEval dataset: {dataset!r}")
        error_type = normalize_type(error_type)
        if error_type not in self._rules:
            raise ValueError(f"Unknown TofuEval error type: {error_type!r}")
        rule = self._rules[error_type]
        if dataset not in rule.datasets or rule.allowed is None:
            return None
        return rule.overrides.get(dataset, rule.allowed)

    def matches(self, error_type: str, dataset: str, predicted_concerns: Iterable[str]) -> bool:
        """Match any allowed concern; unknown/new predictions have no effect."""
        allowed = self.applicable_allowed(error_type, dataset)
        return allowed is not None and not allowed.isdisjoint(predicted_concerns)


def _schema(concerns: list[str]) -> dict:
    allowed = {
        "type": "array", "items": {"enum": concerns}, "minItems": 1, "uniqueItems": True,
    }
    rule = {
        "type": "object",
        "required": ["allowed"],
        "additionalProperties": False,
        "properties": {
            "allowed": {"anyOf": [allowed, {"type": "null"}]},
            "recall_only": {"type": "boolean"},
            "datasets": {
                "type": "array", "items": {"enum": list(_DATASETS)},
                "minItems": 1, "uniqueItems": True,
            },
            "dataset_overrides": {
                "type": "object", "propertyNames": {"enum": list(_DATASETS)},
                "additionalProperties": allowed,
            },
        },
        "if": {"properties": {"recall_only": {"const": True}}, "required": ["recall_only"]},
        "then": {
            "properties": {"allowed": {"type": "null"}},
            "not": {"required": ["dataset_overrides"]},
        },
        "else": {"properties": {"allowed": allowed}},
    }
    return {
        "type": "object",
        "required": ["mapping_version", "semantics", "types"],
        "additionalProperties": False,
        "properties": {
            "mapping_version": {"type": "string", "pattern": _SEMVER},
            "semantics": {"type": "string", "minLength": 1},
            "types": {
                "type": "object", "minProperties": 1,
                "propertyNames": {"minLength": 1}, "additionalProperties": rule,
            },
        },
    }


def load_mapping(path: Path | None = None) -> FrozenMapping:
    """Validate against the current response enum every time, then freeze rules.

    Invalid mapping contents are errors, including removal of a mapped concern
    from the contract. Such drift requires an explicit mapping version decision.
    """
    import json

    path = Path(path) if path is not None else Path(__file__).with_name("mapping.json")
    raw_bytes = path.read_bytes()
    raw = json.loads(raw_bytes)
    concern_enum = contracts.get_contracts().schemas["response"]["$defs"]["Concern"][
        "properties"
    ]["type"]["enum"]
    try:
        Draft202012Validator(_schema(concern_enum)).validate(raw)
    except ValidationError as exc:
        raise ValueError(
            f"Invalid TofuEval mapping (check mapping version/schema drift): {exc.message}"
        ) from exc
    rules = {}
    mapped = set()
    for name, entry in raw["types"].items():
        allowed = frozenset(entry["allowed"]) if entry["allowed"] is not None else None
        overrides = {
            dataset: frozenset(values)
            for dataset, values in entry.get("dataset_overrides", {}).items()
        }
        rules[name] = _Rule(
            allowed, frozenset(entry.get("datasets", _DATASETS)), MappingProxyType(overrides)
        )
        mapped.update(allowed or ())
        for values in overrides.values():
            mapped.update(values)
    return FrozenMapping(
        raw["mapping_version"], sha256(raw_bytes).hexdigest(),
        MappingProxyType(rules), frozenset(mapped),
    )


def applicable_allowed(error_type: str, dataset: str) -> frozenset[str] | None:
    """Convenience lookup using the shipped mapping."""
    return load_mapping().applicable_allowed(error_type, dataset)


def matches(error_type: str, dataset: str, predicted_concerns: Iterable[str]) -> bool:
    """Convenience agreement check using the shipped mapping."""
    return load_mapping().matches(error_type, dataset, predicted_concerns)
