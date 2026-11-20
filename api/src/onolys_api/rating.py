"""Rating-card validation: the one seam `PUT /sessions/{id}/rating` goes through (R2, D15).

The schema is the canonical SP02 one, `rating.schema.json` of the MITI pack (`protocols/
miti-4.2.1/`), loaded through `paudit.pack.load_pack` (honours `PAUDIT_PROTOCOLS_DIR`, which the
image sets to `/app/protocols`). It is the same file the web rating card and the evaluation
engine's `validate_rating` use, so a stored card flows into the engine unchanged. There is no
fallback: a missing or unreadable pack raises, and `create_app` loads it at startup so a bad
deploy fails to boot instead of validating against something else. Issues are paths and codes
only, never card text.
"""

import json
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

from jsonschema import Draft202012Validator
from paudit.pack import load_pack

from onolys_api.adapters.real import PACK_REF

SCHEMA_VERSION = "miti-1"
# Hard cap on a stored card (UTF-8 JSON bytes): bounds unknown keys the shape check does not cover.
MAX_CARD_BYTES = 256 * 1024

_CODES = {
    "maxLength": "too_long",
    "additionalProperties": "unknown_key",
    "required": "required",
}


@dataclass(frozen=True)
class Issue:
    path: str  # dotted card path; never card text
    code: str  # too_long | unknown_key | required | invalid | order | too_large


@lru_cache(maxsize=1)
def load_schema() -> dict[str, Any]:
    """The pack's rating schema; raises `paudit` `PackError` when the pack cannot be loaded."""
    return load_pack(PACK_REF).rating_schema


def card_size(obj: Any) -> int:
    return len(json.dumps(obj, ensure_ascii=False, default=str).encode())


def validate_rating(obj: Any, final: bool) -> list[Issue]:
    """Issues for a rating card. Draft: shape + limits. Final: also a non-empty `change_goal`."""
    if not isinstance(obj, dict):
        return [Issue("", "invalid")]
    issues: list[Issue] = []
    if card_size(obj) > MAX_CARD_BYTES:
        issues.append(Issue("", "too_large"))
    for e in Draft202012Validator(load_schema()).iter_errors(obj):
        code = _CODES.get(e.validator, "invalid")
        issues.append(Issue(".".join(str(p) for p in e.absolute_path), code))
    span = obj.get("coded_span")
    if isinstance(span, dict):
        a, b = span.get("from_s"), span.get("to_s")
        if _num(a) and _num(b) and a > b:
            issues.append(Issue("coded_span", "order"))
    if final:
        goal = obj.get("change_goal")
        if not isinstance(goal, str) or not goal.strip():
            issues.append(Issue("change_goal", "required"))
    return issues


def draft_issues(obj: Any) -> list[Issue]:
    """What a draft autosave is rejected for: size limits only (never incompleteness)."""
    if not isinstance(obj, dict):
        return [Issue("", "invalid")]
    return [i for i in validate_rating(obj, final=False) if i.code in ("too_long", "too_large")]


def _num(v: Any) -> bool:
    return isinstance(v, int | float) and not isinstance(v, bool)


def has_content(card: dict[str, Any]) -> bool:
    """True when the card carries any score, count or non-blank notes ("no rating" otherwise)."""
    globals_ = card.get("globals") or {}
    counts = card.get("counts") or {}
    if any(isinstance(g, dict) and g.get("score") is not None for g in globals_.values()):
        return True
    if any(isinstance(c, dict) and c.get("count") is not None for c in counts.values()):
        return True
    notes = card.get("notes")
    return isinstance(notes, str) and bool(notes.strip())
