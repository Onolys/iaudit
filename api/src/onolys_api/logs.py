"""Structured, PHI-free API logs (PRD R10).

One JSON object per line on stderr: Cloud Logging reads `severity` and `message` and exposes
the rest as `jsonPayload.*` (SP06's alert filters on `jsonPayload.status="failed"`, the runbook on
`jsonPayload.request_id`). Field names pass the `onolys_core.safe_log` allowlist, so text-like or
unknown names are dropped; string values are capped. Values are ids, codes and numbers only.
"""

import hashlib
import hmac
import json
import logging
import sys
import threading

from onolys_core.safe_log import MAX_VALUE_CHARS, register_fields, safe_fields

from onolys_api.config import Settings

API_FIELDS = frozenset({
    "uid_hash", "session_id", "run_id", "step", "status", "attempt", "duration_ms",
    "auth_kind", "error_code", "exc_class", "request_id", "code_version",
    "method", "route", "stt_operation", "stt_started", "poll_n", "elapsed_s", "outcome",
    "state", "swept", "limit_s",
})  # fmt: skip
register_fields(API_FIELDS)

log = logging.getLogger("onolys_api.events")
_LEVELS = {logging.DEBUG: "DEBUG", logging.INFO: "INFO", logging.WARNING: "WARNING",
           logging.ERROR: "ERROR", logging.CRITICAL: "CRITICAL"}  # fmt: skip
_state = {"key": b"", "code_version": "dev"}
_lock = threading.Lock()


class _StderrHandler(logging.StreamHandler):
    """Writes to whatever sys.stderr is at emit time (survives stream swaps)."""

    _onolys = True

    def __init__(self) -> None:
        super().__init__(sys.stderr)

    @property
    def stream(self):
        return sys.stderr

    @stream.setter
    def stream(self, _value) -> None:
        pass


def configure(settings: Settings) -> None:
    """Set the HMAC key and code version, and attach the stderr handler once."""
    with _lock:
        _state["key"] = settings.uid_hmac_key.encode()
        _state["code_version"] = settings.git_sha
        if log.level == logging.NOTSET:
            log.setLevel(logging.INFO)
        if not any(getattr(h, "_onolys", False) for h in log.handlers):
            h = _StderrHandler()
            h.setFormatter(logging.Formatter("%(message)s"))
            log.addHandler(h)


def uid_hash(uid: str) -> str:
    """Keyed HMAC-SHA256 of the uid (first 16 hex chars): correlates a user, reveals nothing."""
    return hmac.new(_state["key"], uid.encode(), hashlib.sha256).hexdigest()[:16]


def _clean(value):
    if value is None:
        return None
    if isinstance(value, bool | int | float):
        return value
    return str(value)[:MAX_VALUE_CHARS]


def emit(event: str, level: int = logging.INFO, **fields) -> None:
    """Log one line. None values are omitted; `code_version` is always added."""
    kept = {k: _clean(v) for k, v in safe_fields(fields).items() if v is not None}
    kept.setdefault("code_version", _state["code_version"])
    line = {"severity": _LEVELS.get(level, "INFO"), "message": event, "event": event, **kept}
    log.log(level, "%s", json.dumps(line, sort_keys=False))


def failed(
    event: str, *, session_id, step, error_code, exc_class, request_id=None, run_id=None
) -> None:
    """The one `status=failed` line of a failed step or run (SP06 alert + runbook match it)."""
    emit(
        event, logging.ERROR, status="failed", session_id=session_id, run_id=run_id, step=step,
        error_code=error_code, exc_class=exc_class, request_id=request_id,
    )  # fmt: skip
