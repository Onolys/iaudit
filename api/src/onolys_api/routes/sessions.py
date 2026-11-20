"""`/v1/sessions`: create (idempotent), list, get. Mutations return 202 with ids (R2)."""

import hashlib
import logging
import re
from datetime import UTC, datetime, timedelta
from typing import Annotated
from uuid import uuid4

from fastapi import APIRouter, Depends, Header, Query, Request, Response
from pydantic import BaseModel, Field, field_validator

from onolys_api.auth.deps import AuthUser, current_user
from onolys_api.errors import ApiError, ErrorResponse
from onolys_api.jobs.delete import delete_session_data
from onolys_api.jobs.machine import advance
from onolys_api.jobs.queue import TaskPayload
from onolys_api.presets import UnknownPreset
from onolys_api.repo.base import NotFoundError
from onolys_api.repo.models import IdempotencyDoc, SessionDoc, SessionState, SessionStatusDoc

log = logging.getLogger("onolys_api.sessions")
IDEMPOTENCY_TTL = timedelta(hours=24)
MAX_KEY_LEN = 200
_BCP47 = re.compile(r"^[A-Za-z]{2,3}(-[A-Za-z0-9]{2,8}){0,3}$")

ERRORS = {"default": {"model": ErrorResponse, "description": "Error"}}
router = APIRouter(prefix="/sessions", tags=["sessions"], responses=ERRORS)
User = Annotated[AuthUser, Depends(current_user)]


class CreateSessionRequest(BaseModel):
    language: str = Field("auto", description="BCP-47 tag or `auto`")
    n_runs: int = Field(1, ge=1, le=5)
    preset: str | None = Field(None, max_length=64, description="Allowlisted preset name")
    title: str | None = Field(None, max_length=200)

    @field_validator("language")
    @classmethod
    def _language(cls, v: str) -> str:
        if v != "auto" and not _BCP47.match(v):
            raise ValueError("invalid language")
        return v


class SessionRef(BaseModel):
    id: str
    status: SessionState


class CreateSessionResponse(BaseModel):
    session: SessionRef


class SessionListItem(BaseModel):
    id: str
    title: str | None = None
    status: SessionState
    created_at: datetime
    latest_report_version: int | None = None
    error_code: str | None = None


class SessionList(BaseModel):
    items: list[SessionListItem]
    next_cursor: str | None = None


class Flags(BaseModel):
    transcript_ready: bool
    speaker_confirmed: bool
    rating_submitted: bool
    has_rating: bool


class SessionErrorInfo(BaseModel):
    code: str


class SessionDetail(BaseModel):
    id: str
    title: str | None = None
    status: SessionState
    step: str | None = None
    progress: int
    flags: Flags
    warnings: list[str]
    error: SessionErrorInfo | None = None
    latest_report_version: int | None = None
    language: str
    n_runs: int
    preset: str | None = None
    created_at: datetime
    updated_at: datetime
    links: dict[str, str]


def _body_hash(body: CreateSessionRequest) -> str:
    return hashlib.sha256(body.model_dump_json().encode()).hexdigest()


def _replay(doc: IdempotencyDoc, body_hash: str, response: Response) -> CreateSessionResponse:
    if doc.body_hash != body_hash:
        raise ApiError.of(409, "conflict", "Idempotency-Key was used with a different request.")
    response.headers["Idempotent-Replayed"] = "true"
    return CreateSessionResponse.model_validate(doc.response)


@router.post(
    "",
    operation_id="createSession",
    status_code=202,
    response_model=CreateSessionResponse,
    summary="Create a session",
    description=(
        "Writes the session and its PHI-free `session_status` document before returning. "
        "`Idempotency-Key` replays the original response for 24 h; the same key with a different "
        "body is 409 `conflict`."
    ),
)
def create_session(
    request: Request,
    response: Response,
    body: CreateSessionRequest,
    user: User,
    idempotency_key: Annotated[
        str | None,
        Header(
            alias="Idempotency-Key",
            min_length=1,
            max_length=MAX_KEY_LEN,
            description="Client-chosen key; replays for 24 h",
        ),
    ] = None,
) -> CreateSessionResponse:
    repo = request.app.state.repo
    uid = user.uid
    body_hash = _body_hash(body)
    now = datetime.now(UTC)

    if idempotency_key:
        prior = repo.get_idempotency(uid, idempotency_key)
        if prior is not None and now - prior.created_at < IDEMPOTENCY_TTL:
            return _replay(prior, body_hash, response)
        if prior is not None:
            repo.delete_idempotency(uid, idempotency_key)  # expired

    try:
        preset, stt = request.app.state.presets.resolve(body.preset, body.language)
    except UnknownPreset:
        raise ApiError.of(422, "invalid_parameters", "preset: unknown preset") from None

    sid = uuid4().hex
    repo.create_session(
        uid,
        sid,
        SessionDoc(
            uid=uid,
            title=body.title,
            language=body.language,
            stt=stt,
            n_runs=body.n_runs,
            preset=preset,
            created_at=now,
            updated_at=now,
        ),
        SessionStatusDoc(uid=uid, updated_at=now),
    )
    result = CreateSessionResponse(session=SessionRef(id=sid, status="created"))

    if idempotency_key:
        stored = IdempotencyDoc(
            body_hash=body_hash, response=result.model_dump(mode="json"), created_at=now
        )
        if not repo.put_idempotency(uid, idempotency_key, stored):
            # lost a race with the same key: drop our session, answer with the winner's
            repo.delete_session(uid, sid)
            winner = repo.get_idempotency(uid, idempotency_key)
            if winner is not None:
                return _replay(winner, body_hash, response)
    return result


@router.get(
    "",
    operation_id="listSessions",
    response_model=SessionList,
    summary="The caller's sessions, newest first (in-flight and failed included)",
)
def list_sessions(
    request: Request,
    user: User,
    limit: Annotated[int, Query(ge=1, le=50)] = 20,
    cursor: Annotated[str | None, Query(max_length=512)] = None,
) -> SessionList:
    try:
        page = request.app.state.repo.list_sessions(user.uid, limit=limit, cursor=cursor)
    except NotFoundError:
        raise ApiError.of(422, "invalid_parameters", "cursor: invalid cursor") from None
    items = [
        SessionListItem(
            id=s.id,
            title=s.title,
            status=s.state,
            created_at=s.created_at,
            latest_report_version=s.latest_report_version,
            error_code=s.error.code if s.error else None,
        )
        for s in page.items
        if s.state != "deleting"
    ]
    return SessionList(items=items, next_cursor=page.next_cursor)


@router.get(
    "/{id}",
    operation_id="getSession",
    response_model=SessionDetail,
    summary="Session status snapshot (the web app uses the session_status listener instead)",
)
def get_session(id: str, request: Request, user: User) -> SessionDetail:
    repo = request.app.state.repo
    s = repo.get_session(user.uid, id)
    if s.state == "deleting":
        raise NotFoundError()
    st = repo.get_status(user.uid, id)
    base = f"/v1/sessions/{id}"
    links = {"self": base}
    if s.transcript_ready:
        links["transcript"] = f"{base}/transcript"
    if s.latest_report_version:
        links["reports"] = f"{base}/reports"
    return SessionDetail(
        id=id,
        title=s.title,
        status=s.state,
        step=st.step,
        progress=st.progress,
        flags=Flags(
            transcript_ready=s.transcript_ready,
            speaker_confirmed=s.speaker_confirmed,
            rating_submitted=s.rating_submitted,
            has_rating=s.has_rating,
        ),
        warnings=s.warnings,
        error={"code": s.error.code} if s.error else None,
        latest_report_version=s.latest_report_version,
        language=s.language,
        n_runs=s.n_runs,
        preset=s.preset,
        created_at=s.created_at,
        updated_at=s.updated_at,
        links=links,
    )


@router.delete(
    "/{id}",
    operation_id="deleteSession",
    status_code=204,
    response_class=Response,
    summary="Hard delete: audio, transcript, ratings, runs, reports, status",
    description=(
        "Marks the session `deleting`, removes every stored object and document, then answers "
        "204. If storage or Firestore fails the session stays `deleting` (hidden everywhere), a "
        "cleanup task finishes it, and this call answers 503 `upstream_unavailable`: repeat it "
        "or wait. Deleting a finished session again answers 404. Usage counters are kept."
    ),
)
def delete_session(id: str, request: Request, user: User) -> Response:
    repo, blobs = request.app.state.repo, request.app.state.blobs
    rid = getattr(request.state, "request_id", None)
    s = repo.get_session(user.uid, id)  # 404 for another user's or an unknown session
    if s.state != "deleting":
        advance(repo, user.uid, id, to="deleting")
    try:
        delete_session_data(repo, blobs, user.uid, id, rid)
    except Exception as e:
        log.error("session_delete_failed exc_class=%s request_id=%s", type(e).__name__, rid)
        queue = getattr(request.app.state, "queue", None)
        try:
            if queue is not None:
                queue.enqueue(TaskPayload(kind="delete", uid=user.uid, sid=id, request_id=rid))
        except Exception as qe:
            log.error("delete_enqueue_failed exc_class=%s request_id=%s", type(qe).__name__, rid)
        raise ApiError.of(
            503, "upstream_unavailable", "Deletion is in progress; it will finish shortly."
        ) from None
    return Response(status_code=204)
