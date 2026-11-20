"""`/v1/sessions/{id}/audio`: signed upload, complete, signed read (R2 audio, R3, D5)."""

from datetime import UTC, datetime, timedelta
from typing import Annotated
from uuid import uuid4

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field

from onolys_api.audio import (
    CANONICAL_TYPES,
    original_key,
    resolve_format,
    staging_key,
)
from onolys_api.auth.deps import AuthUser, current_user
from onolys_api.errors import ApiError, ErrorResponse
from onolys_api.jobs.machine import advance, invalid_state
from onolys_api.jobs.queue import TaskPayload
from onolys_api.repo.base import NotFoundError
from onolys_api.routes.sessions import SessionRef
from onolys_api.storage.base import MAX_UPLOAD_BYTES, READ_URL_TTL_S, BlobNotFoundError

ERRORS = {"default": {"model": ErrorResponse, "description": "Error"}}
router = APIRouter(prefix="/sessions/{id}/audio", tags=["audio"], responses=ERRORS)
User = Annotated[AuthUser, Depends(current_user)]


class AudioUploadRequest(BaseModel):
    content_type: str = Field("", max_length=100, description="Browser type; may be empty")
    size_bytes: int = Field(ge=1, description="File size; above 300 MB is `audio_too_large`")
    filename_ext: str = Field("", max_length=16, description="Used only when content_type is empty")


class AudioUploadResponse(BaseModel):
    upload_url: str
    upload_id: str
    required_headers: dict[str, str] = Field(
        description="Send exactly these headers with the PUT (the canonical Content-Type)"
    )


class AudioReadResponse(BaseModel):
    url: str
    expires_at: datetime


def _owned_open(request: Request, user: AuthUser, id: str):
    s = request.app.state.repo.get_session(user.uid, id)
    if s.state == "deleting":
        raise NotFoundError()
    return s


@router.post(
    "",
    operation_id="requestAudioUpload",
    response_model=AudioUploadResponse,
    summary="Get a signed PUT URL for the recording",
    description=(
        "Maps browser aliases (`audio/x-m4a`, `audio/mp4`, `audio/mpeg`, empty type + "
        "`filename_ext`) to one canonical type, returns one signed PUT (15 min) pinned to it and "
        "to a 300 MB size range; the client sends exactly `required_headers`. Unknown type is "
        "422 `unsupported_audio`, over 300 MB is 422 `audio_too_large`. State becomes `uploading`."
    ),
)
def request_upload(
    id: str, body: AudioUploadRequest, request: Request, user: User
) -> AudioUploadResponse:
    fmt = resolve_format(body.content_type, body.filename_ext)
    if fmt is None:
        raise ApiError.of(422, "unsupported_audio", "The audio type is not supported.")
    if body.size_bytes > MAX_UPLOAD_BYTES:
        raise ApiError.of(422, "audio_too_large", "The audio file is larger than 300 MB.")
    repo, blobs = request.app.state.repo, request.app.state.blobs
    session = _owned_open(request, user, id)
    advance(repo, user.uid, id, to="uploading")  # 409 invalid_state unless created|uploading
    if session.upload is not None:  # a fresh URL replaces the earlier one
        blobs.delete(staging_key(user.uid, id, session.upload.upload_id))
    upload_id = uuid4().hex
    canonical = CANONICAL_TYPES[fmt]
    signed = blobs.signed_upload(staging_key(user.uid, id, upload_id), canonical, MAX_UPLOAD_BYTES)
    repo.update_session(
        user.uid,
        id,
        {
            "upload": {
                "upload_id": upload_id,
                "format": fmt,
                "content_type": canonical,
                "size_bytes": body.size_bytes,
            }
        },
    )
    return AudioUploadResponse(
        upload_url=signed.url, upload_id=upload_id, required_headers=signed.headers
    )


@router.post(
    "/complete",
    operation_id="completeAudioUpload",
    status_code=202,
    response_model=dict[str, SessionRef],
    summary="Tell the server the PUT finished",
    description="Returns 202 and enqueues `validate`; transcription starts after it passes.",
)
def complete_upload(id: str, request: Request, user: User) -> dict[str, SessionRef]:
    repo, blobs = request.app.state.repo, request.app.state.blobs
    try:
        session = _owned_open(request, user, id)
    except NotFoundError:
        # a signed PUT that landed after a DELETE staged a blob nothing else would sweep
        # (the bucket lifecycle rule is the backstop); `user.uid` scopes this to the caller
        blobs.delete_prefix(f"uploads/{user.uid}/{id}/")
        raise
    if session.state not in ("uploading", "validating") or session.upload is None:
        raise invalid_state()
    if not blobs.exists(staging_key(user.uid, id, session.upload.upload_id)):
        raise ApiError.of(409, "invalid_state", "No uploaded audio was found for this session.")
    queue = getattr(request.app.state, "queue", None)
    if queue is None:
        raise ApiError.of(503, "upstream_unavailable", "Service temporarily unavailable.")
    if session.state == "uploading":
        advance(repo, user.uid, id, to="validating", step="validate")
    queue.enqueue(
        TaskPayload(
            kind="validate",
            uid=user.uid,
            sid=id,
            request_id=getattr(request.state, "request_id", None),
        )
    )  # name-deduplicated: a repeated `complete` is harmless
    return {"session": SessionRef(id=id, status="validating")}


@router.get(
    "",
    operation_id="getAudio",
    response_model=AudioReadResponse,
    summary="Short-lived signed read URL for the original upload",
)
def get_audio(id: str, request: Request, user: User) -> AudioReadResponse:
    repo, blobs = request.app.state.repo, request.app.state.blobs
    _owned_open(request, user, id)
    recording = next((r for r in repo.list_recordings(user.uid, id) if r.format), None)
    if recording is None or recording.format not in CANONICAL_TYPES:
        raise NotFoundError()
    key = original_key(user.uid, id, recording.format)
    if not blobs.exists(key):
        raise NotFoundError()
    try:
        url = blobs.signed_read_url(key, READ_URL_TTL_S)
    except BlobNotFoundError:
        raise NotFoundError() from None
    return AudioReadResponse(
        url=url, expires_at=datetime.now(UTC) + timedelta(seconds=READ_URL_TTL_S)
    )
