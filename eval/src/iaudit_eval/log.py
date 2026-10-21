"""PHI-safe logging: an allowlist of field names; text-like names are always dropped."""

import json
import logging

logger = logging.getLogger("iaudit_eval")

ALLOWED_FIELDS = frozenset(
    {
        "run_id",
        "item_id",
        "status",
        "state",
        "kind",
        "http_status",
        "attempt",
        "items_total",
        "items_done",
        "items_ok",
        "items_failed",
        "count",
        "counts",
        "duration_ms",
        "total_ms",
        "elapsed_ms",
        "exc_class",
        "dataset",
        "split",
    }
)
_BLOCKED_PARTS = ("text", "body", "transcript", "excerpt", "message", "payload", "response")
MAX_VALUE_CHARS = 200


def _blocked(name: str) -> bool:
    return any(p in name for p in _BLOCKED_PARTS)


def _fmt(value) -> str:
    """Numbers bare; everything else a capped, JSON-escaped string (no CR/LF, no forged fields)."""
    if isinstance(value, bool | int | float):
        return str(value)
    return json.dumps(str(value)[:MAX_VALUE_CHARS])


def log_event(event: str, level: int = logging.INFO, **fields) -> None:
    kept = {k: v for k, v in fields.items() if k in ALLOWED_FIELDS and not _blocked(k)}
    pairs = " ".join(f"{k}={_fmt(v)}" for k, v in sorted(kept.items()))
    logger.log(level, "%s %s", event, pairs)
