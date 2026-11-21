"""Lazy stale check (no cron): fail a session whose poll chain stopped without a terminal state.

A session still `transcribing` more than its cap (`steps.transcribe.stt_limit_s`, else the
settings maximum) + 60 s after its last write (`updated_at`: entering `transcribing` / storing
the operation; polls write nothing until they finish it) has lost its chain: Cloud Tasks gave up
or a task was dropped. It is failed with `transcription_failed` when read, in one repo
transaction that re-checks the state, so a poll that finished in the meantime wins.
"""

from datetime import datetime, timedelta

from onolys_api import logs
from onolys_api.config import Settings
from onolys_api.repo.base import NotFoundError, Repo
from onolys_api.repo.models import SessionDoc, SessionError

STALE_MARGIN_S = 60
STEP = "transcribe"


def _cutoff(s: SessionDoc, now: datetime, settings: Settings) -> datetime:
    rec = s.steps.get(STEP)
    limit = (rec.stt_limit_s if rec else None) or settings.stt_time_limit_s
    return now - timedelta(seconds=limit + STALE_MARGIN_S)


def settle_if_stale(repo: Repo, s: SessionDoc, now: datetime, settings: Settings) -> SessionDoc:
    """`s`, or its fresh copy after trying to fail it because its chain is dead (the transaction
    may find it moved on: a finished poll wins)."""
    cutoff = _cutoff(s, now, settings)
    if s.state != "transcribing" or s.updated_at >= cutoff:
        return s
    try:
        failed = repo.fail_stale_session(
            s.uid, s.id, "transcribing", cutoff,
            SessionError(code="transcription_failed", step=STEP),
        )  # fmt: skip
    except NotFoundError:
        return s
    if failed:
        logs.failed(
            "session_stale", session_id=s.id, step=STEP, error_code="transcription_failed",
            exc_class="StaleSession",
        )  # fmt: skip
    return repo.get_session(s.uid, s.id)
