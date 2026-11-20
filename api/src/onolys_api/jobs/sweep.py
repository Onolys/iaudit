"""Stale-status sweeper (SP04): fail sessions whose task chain broke and left them in-progress.

The in-chain limits (`STT_TIME_LIMIT_S` in a poll, the validate deadline) only run while the task
chain lives. If the next-poll enqueue fails after Cloud Tasks gives up, or a task is dropped, the
session would stay `transcribing` (or `validating`) forever. Cloud Scheduler calls
`POST /tasks/sweep-stale` every 10 minutes; each in-progress state has a limit (the chain's own
limit plus a margin) measured from the session's last write (`updated_at`, which a healthy chain
refreshes at every state/step change). Older sessions are failed with the same public error the
chain would have used. `Repo.fail_stale_session` re-checks state and age in one transaction, so a
poll that just finished is never overwritten and a second sweep finds nothing to do.

`running` is not swept: its failure path also releases the user's run slot and the run record.
Logs carry ids and codes only.
"""

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta

from onolys_api import logs
from onolys_api.jobs.transcribe import STT_TIME_LIMIT_S
from onolys_api.jobs.worker import DEADLINE_S, LEASE_GRACE_S
from onolys_api.repo.base import NotFoundError, Repo
from onolys_api.repo.models import SessionError

SWEEP_MARGIN_S = 10 * 60
BATCH = 50  # per state per sweep; the next sweep takes the rest


@dataclass(frozen=True)
class StaleRule:
    state: str
    limit_s: float  # in-chain limit + margin
    code: str  # public error code (same as the chain's own failure)
    step: str


_VALIDATE_LIMIT_S = 2 * (DEADLINE_S + LEASE_GRACE_S) + SWEEP_MARGIN_S  # two attempts + backoff
RULES: tuple[StaleRule, ...] = (
    StaleRule(
        "transcribing", STT_TIME_LIMIT_S + SWEEP_MARGIN_S, "transcription_failed", "transcribe"
    ),
    StaleRule("validating", _VALIDATE_LIMIT_S, "deadline_exceeded", "validate"),
)


def sweep_stale(
    repo: Repo, clock: Callable[[], datetime], rules: tuple[StaleRule, ...] = RULES
) -> dict[str, int]:
    """Fail every stale session; returns {state: number failed}."""
    now = clock()
    out: dict[str, int] = {}
    for rule in rules:
        before = now - timedelta(seconds=rule.limit_s)
        error = SessionError(code=rule.code, step=rule.step)
        swept = 0
        for s in repo.list_stale_sessions(rule.state, before, BATCH):
            try:
                if not repo.fail_stale_session(s.uid, s.id, rule.state, before, error):
                    continue  # finished, written to or failed meanwhile
            except NotFoundError:
                continue  # deleted meanwhile
            swept += 1
            logs.failed(
                "session_swept", session_id=s.id, step=rule.step, error_code=rule.code,
                exc_class="StaleSession",
            )  # fmt: skip
        out[rule.state] = swept
        logs.emit(
            "sweep_stale", logging.INFO, state=rule.state, swept=swept, limit_s=int(rule.limit_s)
        )
    return out
