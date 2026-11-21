"""Typed Firestore documents, one per collection in the PRD R7 table.

`id` is the document id: filled on read, never written. Datetimes are tz-aware UTC.
"""

from datetime import UTC, datetime
from typing import Any, Literal

from onolys_core.transcript import Transcript
from pydantic import BaseModel, Field

SessionState = Literal[
    "created",
    "uploading",
    "validating",
    "transcribing",
    "awaiting_input",
    "running",
    "report_ready",
    "failed",
    "deleting",
]
RunStatus = Literal["pending", "running", "done", "failed"]
StepStatus = Literal["pending", "running", "done", "failed"]


def utcnow() -> datetime:
    return datetime.now(UTC)


class Doc(BaseModel):
    id: str = ""

    def to_store(self) -> dict[str, Any]:
        return self.model_dump(mode="python", exclude={"id"})


class BlobPointer(BaseModel):
    """Firestore holds this instead of an object larger than 500 KB (D11)."""

    key: str
    uri: str
    size_bytes: int


class UserDoc(Doc):
    created_at: datetime = Field(default_factory=utcnow)
    prefs: dict[str, Any] = Field(default_factory=dict)
    expiry_days: int | None = None
    daily_cap: int | None = None  # per-user override of DAILY_RUN_CAP (R8)
    max_active_runs: int | None = None  # per-user override of MAX_ACTIVE_RUNS (R8)
    active_runs: int = 0  # runs reserved and not yet released (R8 concurrent limit)


class SttInfo(BaseModel):
    provider: str = ""
    model: str = ""
    language: str = ""


class CodedSpan(BaseModel):
    from_s: float
    to_s: float


class StepRecord(BaseModel):
    status: StepStatus = "pending"
    attempts: int = 0
    started: datetime | None = None
    ended: datetime | None = None
    error: str | None = None
    stt_operation: Any = None  # opaque handle from SttAdapter.start (transcribe step only)
    stt_started: datetime | None = None  # when `start` returned: the poll time limit runs from it
    stt_limit_s: float | None = None  # this recording's poll cap (None: the settings maximum)


class UploadInfo(BaseModel):
    """The signed PUT in flight (staging object `uploads/{uid}/{sid}/{upload_id}`)."""

    upload_id: str
    format: str  # canonical format key: mp3 | wav | m4a | webm | ogg
    content_type: str
    size_bytes: int


class SessionError(BaseModel):
    code: str
    step: str | None = None


class SessionDoc(Doc):
    uid: str
    title: str | None = None
    state: SessionState = "created"
    step: str | None = None
    language: str = "auto"
    stt: SttInfo | None = None
    change_goal: str | None = None
    coded_span: CodedSpan | None = None
    n_runs: int = 1
    preset: str | None = None
    clinician_speaker: str | None = None
    transcript_ready: bool = False
    speaker_confirmed: bool = False
    rating_submitted: bool = False
    has_rating: bool = False
    first_run_id: str | None = None
    upload: UploadInfo | None = None
    steps: dict[str, StepRecord] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)
    error: SessionError | None = None
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)
    latest_report_version: int | None = None


class SessionStatusDoc(Doc):
    """The only client-readable document: no transcript, rating, report text or PHI."""

    uid: str
    state: SessionState = "created"
    step: str | None = None
    progress: int = 0
    error_code: str | None = None
    latest_report_version: int | None = None
    updated_at: datetime = Field(default_factory=utcnow)
    transcript_ready: bool = False
    speaker_confirmed: bool = False
    rating_submitted: bool = False
    has_rating: bool = False


class RecordingDoc(Doc):
    gcs_uri: str
    size: int | None = None
    duration_ms: int | None = None
    format: str | None = None
    sha256: str | None = None


class TranscriptDoc(Doc):
    transcript: Transcript | None = None  # None when stored out of line (pointer set)
    pointer: BlobPointer | None = None
    created_at: datetime = Field(default_factory=utcnow)


class RatingDoc(Doc):
    """One final revision (`ratings/{rating_id}`). Firestore only."""

    card: dict[str, Any]
    no_rating: bool = False
    has_rating: bool = True
    schema_version: str = ""
    created_at: datetime = Field(default_factory=utcnow)


class RatingDraftDoc(Doc):
    """The single autosaved draft (`ratings/draft`), overwritten in place."""

    card: dict[str, Any]
    updated_at: datetime = Field(default_factory=utcnow)


class RunDoc(Doc):
    uid: str
    session_id: str
    run_id: str
    n_runs: int = 1
    preset: str | None = None
    rating_id: str | None = None
    stt: SttInfo | None = None
    code_version: str = ""
    status: RunStatus = "pending"
    attempts: int = 0
    stage: str | None = None
    started: datetime | None = None
    ended: datetime | None = None
    error: str | None = None
    run_info: dict[str, Any] | None = None
    artifacts_prefix: str | None = None
    cap_date: str | None = None  # UTC day the cap slot was reserved on (R8)
    released: bool = False  # the cap slot was handed back: guards double release


class ReportDoc(Doc):
    version: int
    run_id: str
    report: dict[str, Any] | None = None  # None when stored out of line (pointer set)
    pointer: BlobPointer | None = None
    report_schema_version: str = ""
    created_at: datetime = Field(default_factory=utcnow)


class ApiKeyDoc(Doc):
    uid: str
    hash: str
    created: datetime = Field(default_factory=utcnow)
    revoked_at: datetime | None = None
    last_used_at: datetime | None = None


class UsageDoc(Doc):
    uid: str = ""
    date: str = ""
    runs: int = 0
    tokens: int = 0


class IdempotencyDoc(Doc):
    body_hash: str
    response: dict[str, Any]
    created_at: datetime = Field(default_factory=utcnow)
