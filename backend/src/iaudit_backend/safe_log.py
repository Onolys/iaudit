"""PHI-safe logging: an allowlist of field names; text-like names are always dropped."""

import logging

log = logging.getLogger("iaudit")

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
        "exc_class",
        "frames",
    }
)
_BLOCKED_PARTS = ("text", "body", "transcript", "excerpt", "message")


def _blocked(name: str) -> bool:
    # body_bytes is a size, not content
    return name != "body_bytes" and any(p in name for p in _BLOCKED_PARTS)


def log_event(event: str, level: int = logging.INFO, **fields) -> None:
    kept = {k: v for k, v in fields.items() if k in ALLOWED_FIELDS and not _blocked(k)}
    pairs = " ".join(f"{k}={v}" for k, v in sorted(kept.items()))
    log.log(level, "%s %s", event, pairs)
