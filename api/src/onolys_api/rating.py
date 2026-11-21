"""Rating-card validation: the one seam `PUT /sessions/{id}/rating` goes through (R2, D15).

A thin wrapper over the evaluation engine's `onolys_evaluation.rating` (`validate_rating`,
`is_no_rating`), so a card the API stores is one the engine accepts, with the engine's rules (pack
item ids, score scales, counts and spans >= 0, limits) and its issue format (`Issue(path, code)`,
`/`-joined paths). The only API-only rule is the HTTP size cap `MAX_CARD_BYTES`. The pack is
loaded through `paudit.pack.load_pack` (honours `PAUDIT_PROTOCOLS_DIR`, which the image sets to
`/app/protocols`). There is no fallback: a missing or unreadable pack raises, and `create_app`
loads it at startup so a bad deploy fails to boot. Issues are paths and codes only, never card text.
"""

import json
from functools import lru_cache
from typing import Any

from onolys_evaluation.rating import is_no_rating
from onolys_evaluation.rating import validate_rating as engine_validate_rating
from onolys_evaluation.report import Issue
from paudit.pack import Pack, load_pack

from onolys_api.adapters.real import PACK_REF

SCHEMA_VERSION = "miti-1"
# Hard cap on a stored card (UTF-8 JSON bytes): bounds unknown keys the shape check does not cover.
MAX_CARD_BYTES = 256 * 1024

__all__ = ["MAX_CARD_BYTES", "SCHEMA_VERSION", "Issue", "has_content", "validate_rating"]


@lru_cache(maxsize=1)
def load_pack_cached() -> Pack:
    """The MITI pack; raises `paudit` `PackError` when it cannot be loaded."""
    return load_pack(PACK_REF)


def load_schema() -> dict[str, Any]:
    """The pack's rating schema (the canonical SP02 `rating.schema.json`)."""
    return load_pack_cached().rating_schema


def card_size(obj: Any) -> int:
    return len(json.dumps(obj, ensure_ascii=False, default=str).encode())


def validate_rating(obj: Any, final: bool) -> list[Issue]:
    """Engine issues for a card, plus `too_large` over the size cap.

    `final=False` (autosave): shape and limits only. `final=True`: also a non-empty `change_goal`.
    """
    issues = list(engine_validate_rating(load_pack_cached(), obj, final))
    if card_size(obj) > MAX_CARD_BYTES:
        issues.insert(0, Issue(path="", code="too_large"))
    return issues


def has_content(card: dict[str, Any]) -> bool:
    """True when the card carries any score, count or non-blank notes ("no rating" otherwise)."""
    return not is_no_rating(card)
