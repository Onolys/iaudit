"""The `Repo` protocol: the single uid-checked choke point for Firestore (R7, D7).

Every call takes `uid` first. A document that is missing, or owned by another uid, raises
`NotFoundError` (HTTP 404, never 403) with identical text, so ids cannot be probed.
Sync on purpose: routes/handlers call it from threadpool workers.
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Literal, Protocol

from onolys_core.transcript import Transcript

from onolys_api.errors import ApiError
from onolys_api.repo.models import (
    ApiKeyDoc,
    IdempotencyDoc,
    RatingDoc,
    RatingDraftDoc,
    RecordingDoc,
    ReportDoc,
    RunDoc,
    SessionDoc,
    SessionStatusDoc,
    TranscriptDoc,
    UsageDoc,
    UserDoc,
)


class NotFoundError(ApiError):
    def __init__(self) -> None:
        super().__init__(
            404, "Resource not found.", [{"code": "not_found", "message": "Resource not found."}]
        )


class ConflictError(ApiError):
    def __init__(self) -> None:
        super().__init__(409, "Conflict.", [{"code": "conflict", "message": "Conflict."}])


@dataclass
class Page[T]:
    items: list[T] = field(default_factory=list)
    next_cursor: str | None = None


ClaimOutcome = Literal["claimed", "done", "failed", "busy"]


@dataclass(frozen=True)
class Claim:
    """Result of claiming a step/run record: `claimed` (caller owns it now, `attempts` counts
    claims), `done`/`failed` (terminal: a duplicate delivery), `busy` (running inside its lease)."""

    outcome: ClaimOutcome
    attempts: int = 0


def decide_claim(
    status: str | None, started: datetime | None, attempts: int, now: datetime, lease_s: float
) -> Claim:
    """Shared claim rule. A `running` record older than the lease is re-claimable."""
    if status in ("done", "failed"):
        return Claim(status, attempts)  # type: ignore[arg-type]
    if status == "running" and started is not None and now < started + timedelta(seconds=lease_s):
        return Claim("busy", attempts)
    return Claim("claimed", attempts + 1)


class Repo(Protocol):
    # users
    def get_user(self, uid: str) -> UserDoc | None: ...
    def ensure_user(self, uid: str) -> UserDoc: ...

    # sessions + session_status (one batch for create; update mirrors `status`)
    def create_session(
        self, uid: str, sid: str, session: SessionDoc, status: SessionStatusDoc
    ) -> None: ...
    def get_session(self, uid: str, sid: str) -> SessionDoc: ...
    def get_status(self, uid: str, sid: str) -> SessionStatusDoc: ...
    def update_session(
        self, uid: str, sid: str, fields: dict[str, Any], status: dict[str, Any] | None = None
    ) -> None: ...
    def list_sessions(
        self, uid: str, limit: int = 20, cursor: str | None = None
    ) -> Page[SessionDoc]: ...
    def delete_session(self, uid: str, sid: str) -> bool: ...

    # children of a session
    def add_recording(self, uid: str, sid: str, rid: str, rec: RecordingDoc) -> None: ...
    def list_recordings(self, uid: str, sid: str) -> list[RecordingDoc]: ...
    def put_transcript(self, uid: str, sid: str, tid: str, transcript: Transcript) -> None: ...
    def get_transcript(
        self, uid: str, sid: str, tid: str, resolve: bool = True
    ) -> TranscriptDoc: ...
    def put_rating_revision(self, uid: str, sid: str, rating_id: str, doc: RatingDoc) -> None: ...
    def get_rating(self, uid: str, sid: str, rating_id: str) -> RatingDoc: ...
    def latest_rating(self, uid: str, sid: str) -> RatingDoc | None: ...
    def put_rating_draft(self, uid: str, sid: str, draft: RatingDraftDoc) -> None: ...
    def get_rating_draft(self, uid: str, sid: str) -> RatingDraftDoc | None: ...
    def create_run(self, uid: str, sid: str, run_id: str, run: RunDoc) -> None: ...
    def get_run(self, uid: str, sid: str, run_id: str) -> RunDoc: ...
    def update_run(self, uid: str, sid: str, run_id: str, fields: dict[str, Any]) -> None: ...
    def list_runs(self, uid: str, sid: str) -> list[RunDoc]: ...
    # atomic claim with lease (R5): pending|expired-running -> running, attempts+1
    def claim_step(self, uid: str, sid: str, step: str, now: datetime, lease_s: float) -> Claim: ...
    def claim_run(
        self, uid: str, sid: str, run_id: str, now: datetime, lease_s: float
    ) -> Claim: ...
    def get_run_by_id(self, uid: str, run_id: str) -> RunDoc: ...
    def put_report(self, uid: str, sid: str, report_id: str, doc: ReportDoc) -> None: ...
    def get_report(self, uid: str, sid: str, report_id: str, resolve: bool = True) -> ReportDoc: ...
    def get_report_by_version(
        self, uid: str, sid: str, version: int, resolve: bool = True
    ) -> ReportDoc: ...
    def list_reports(self, uid: str, sid: str) -> list[ReportDoc]: ...

    # api keys. `get_api_key` is the ONE unscoped read: auth looks a key up by id before the
    # uid is known, then compares the secret hash. Everything else is uid-scoped.
    def get_api_key(self, keyid: str) -> ApiKeyDoc | None: ...
    def create_api_key(self, uid: str, keyid: str, doc: ApiKeyDoc) -> None: ...
    def active_api_key(self, uid: str) -> ApiKeyDoc | None: ...
    def revoke_api_key(self, uid: str, keyid: str, at: datetime) -> None: ...
    def mark_api_key_used(self, uid: str, keyid: str, at: datetime) -> None: ...

    # usage + idempotency
    def get_usage(self, uid: str, date: str) -> UsageDoc: ...
    def add_usage(self, uid: str, date: str, runs: int = 0, tokens: int = 0) -> UsageDoc: ...
    def get_idempotency(self, uid: str, key: str) -> IdempotencyDoc | None: ...
    def put_idempotency(self, uid: str, key: str, doc: IdempotencyDoc) -> bool: ...
    def delete_idempotency(self, uid: str, key: str) -> None: ...  # no-op if absent/foreign
