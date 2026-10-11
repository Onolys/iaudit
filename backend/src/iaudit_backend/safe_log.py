"""PHI-safe logging: an allowlist of field names; text-like names are always dropped."""

import json
import logging
import sys

log = logging.getLogger("iaudit")


class _StderrHandler(logging.StreamHandler):
    """Writes to whatever sys.stderr is at emit time (survives stream swaps)."""

    _iaudit = True

    def __init__(self) -> None:
        super().__init__(sys.stderr)

    @property
    def stream(self):
        return sys.stderr

    @stream.setter
    def stream(self, _value) -> None:
        pass


def setup_logging(level: str = "INFO") -> None:
    """Attach one stderr handler to the iaudit logger; safe to call repeatedly."""
    log.setLevel(level)
    if not any(getattr(h, "_iaudit", False) for h in log.handlers):
        h = _StderrHandler()
        h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
        log.addHandler(h)


ALLOWED_FIELDS = frozenset(
    {
        "request_id",
        "audit_uuid",
        "turns",
        "sections",
        "body_bytes",
        "status",
        "outcome",
        "total_ms",
        "calls",
        "calls_ok",
        "input_tokens",
        "output_tokens",
        "cache_read_tokens",
        "cache_write_tokens",
        "models",
        "tier_calls",
        "pairs",
        "undecided",
        "chunks",
        "degraded_chunks",
        "claim_id",
        "mode",
        "shortlist_size",
        "items_returned",
        "items_kept",
        "coerced",
        "section_index",
        "claims",
        "dropped",
        "gaps",
        "retries",
        "failure",
        "exc_class",
        "prep_ms",
        "atomize_ms",
        "link_ms",
        "check_ms",
        "assemble_ms",
        "sections_ok",
        "sections_failed",
        "claims_in_scope",
        "claims_oos",
        "claims_stalled",
        "claims_ok",
        "truncated",
        "deadline_hit",
        "cancelled",
        "called",
        "verdict",
        "row",
        "flags_seen",
        "flags_below_floor",
        "flags_suppressed",
        "items_below_floor",
        "inferences_below_floor",
        "items_dropped",
        "role_skipped",
        "role_disagreements",
        "frames",
    }
)
_BLOCKED_PARTS = ("text", "body", "transcript", "excerpt", "message")


def _blocked(name: str) -> bool:
    # body_bytes is a size, not content
    return name != "body_bytes" and any(p in name for p in _BLOCKED_PARTS)


MAX_VALUE_CHARS = 200


def _fmt(value) -> str:
    """Numbers bare; everything else a capped, JSON-escaped string (no CR/LF, no forged fields)."""
    if isinstance(value, bool | int | float):
        return str(value)
    return json.dumps(str(value)[:MAX_VALUE_CHARS])


def log_event(event: str, level: int = logging.INFO, **fields) -> None:
    kept = {k: v for k, v in fields.items() if k in ALLOWED_FIELDS and not _blocked(k)}
    pairs = " ".join(f"{k}={_fmt(v)}" for k, v in sorted(kept.items()))
    log.log(level, "%s %s", event, pairs)
