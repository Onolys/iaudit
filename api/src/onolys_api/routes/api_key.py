"""`/v1/api-key`: one active key per user. Token auth only; the secret is shown once."""

from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel

from onolys_api.auth.deps import AuthUser, current_user_token_only
from onolys_api.auth.keys import new_key
from onolys_api.errors import ErrorResponse
from onolys_api.repo.models import ApiKeyDoc

ERRORS = {"default": {"model": ErrorResponse, "description": "Error"}}
router = APIRouter(prefix="/api-key", tags=["api-key"], responses=ERRORS)

TokenUser = Annotated[AuthUser, Depends(current_user_token_only)]


class ApiKeyInfo(BaseModel):
    active: bool
    key_id: str | None = None
    created: datetime | None = None
    last_used_at: datetime | None = None


class ApiKeyCreated(BaseModel):
    key_id: str
    api_key: str  # `onolys_<id>_<secret>`; never retrievable again
    created: datetime


@router.get("", operation_id="getApiKey", response_model=ApiKeyInfo, summary="Active key metadata")
def get_api_key(request: Request, user: TokenUser) -> ApiKeyInfo:
    doc = request.app.state.repo.active_api_key(user.uid)
    if doc is None:
        return ApiKeyInfo(active=False)
    return ApiKeyInfo(
        active=True, key_id=doc.id, created=doc.created, last_used_at=doc.last_used_at
    )


@router.post(
    "",
    operation_id="createApiKey",
    status_code=201,
    response_model=ApiKeyCreated,
    summary="Create a key (revokes the current one); the secret is shown once",
)
def create_api_key(request: Request, user: TokenUser) -> ApiKeyCreated:
    repo = request.app.state.repo
    now = datetime.now(UTC)
    old = repo.active_api_key(user.uid)
    if old is not None:
        repo.revoke_api_key(user.uid, old.id, now)
    key_id, full, digest = new_key()
    repo.create_api_key(user.uid, key_id, ApiKeyDoc(uid=user.uid, hash=digest, created=now))
    return ApiKeyCreated(key_id=key_id, api_key=full, created=now)


@router.delete(
    "", operation_id="deleteApiKey", status_code=204, summary="Revoke the active key (idempotent)"
)
def delete_api_key(request: Request, user: TokenUser) -> Response:
    repo = request.app.state.repo
    old = repo.active_api_key(user.uid)
    if old is not None:
        repo.revoke_api_key(user.uid, old.id, datetime.now(UTC))
    return Response(status_code=204)
