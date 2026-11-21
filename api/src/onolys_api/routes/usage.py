"""`GET /v1/usage`: today's run count against the daily cap (R8)."""

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel

from onolys_api.auth.deps import AuthUser, current_user
from onolys_api.errors import ErrorResponse
from onolys_api.jobs import caps

ERRORS = {"default": {"model": ErrorResponse, "description": "Error"}}
router = APIRouter(prefix="/usage", tags=["usage"], responses=ERRORS)
User = Annotated[AuthUser, Depends(current_user)]


class Usage(BaseModel):
    runs_today: int
    daily_cap: int
    resets_at: datetime


@router.get("", operation_id="getUsage", response_model=Usage, summary="Runs used today (UTC day)")
def get_usage(request: Request, user: User) -> Usage:
    runs, cap, resets = caps.usage_view(
        request.app.state.repo, request.app.state.settings, user.uid
    )
    return Usage(runs_today=runs, daily_cap=cap, resets_at=resets)
