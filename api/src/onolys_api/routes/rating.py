"""`/v1/sessions/{id}/rating`: the in-app rating card (R2, D15). Firestore only, no parsing.

`final=false` overwrites the single draft doc (size limits only; never gates or starts a run).
`final=true` validates the card and writes a new revision `ratings/{rating_id}`, copies
`change_goal`/`coded_span` to the session, sets `rating_submitted`/`has_rating`, mirrors them to
`session_status` and calls the first-run hook. Allowed in every state but `deleting` (404).
"""

from datetime import UTC, datetime
from typing import Annotated, Any
from uuid import uuid4

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field

from onolys_api.auth.deps import AuthUser, current_user
from onolys_api.errors import ApiError, ErrorDetail, ErrorResponse
from onolys_api.jobs.first_run import maybe_start_first_run
from onolys_api.rating import SCHEMA_VERSION, Issue, has_content, validate_rating
from onolys_api.repo.base import NotFoundError
from onolys_api.repo.models import RatingDoc, RatingDraftDoc

ERRORS = {"default": {"model": ErrorResponse, "description": "Error"}}
router = APIRouter(prefix="/sessions/{id}/rating", tags=["rating"], responses=ERRORS)
User = Annotated[AuthUser, Depends(current_user)]
INVALID = "The rating card is not valid (shape or length limits)."


class RatingRequest(BaseModel):
    final: bool = Field(description="`false` autosaves the draft; `true` submits a new revision")
    no_rating: bool = Field(False, description='With `final`: submit as a "no rating" revision')
    card: dict[str, Any] = Field(description="The rating card (`rating.schema.json`)")


class RatingSaved(BaseModel):
    final: bool
    rating_id: str | None = None
    no_rating: bool | None = None
    has_rating: bool | None = None
    updated_at: datetime


class FinalRating(BaseModel):
    rating_id: str
    no_rating: bool
    card: dict[str, Any]


class DraftRating(BaseModel):
    card: dict[str, Any]
    updated_at: datetime


class RatingView(BaseModel):
    final: FinalRating | None = None
    draft: DraftRating | None = Field(None, description="Only when newer than the last final")


MAX_ISSUES = 20


def _invalid(issues: list[Issue]) -> ApiError:
    """422 `rating_invalid`: one detail per issue (card path + issue code, never card text)."""
    details: list[ErrorDetail] = []
    for path, code in sorted({(i.path, i.code) for i in issues})[:MAX_ISSUES]:
        field = path or "$"
        details.append(
            {"code": "rating_invalid", "message": f"{field}: {code}", "field": field,
             "issue": code}
        )  # fmt: skip
    return ApiError(422, INVALID, details)


def _open_session(request: Request, user: AuthUser, id: str):
    s = request.app.state.repo.get_session(user.uid, id)
    if s.state == "deleting":
        raise NotFoundError()
    return s


@router.put(
    "",
    operation_id="putRating",
    status_code=202,
    response_model=RatingSaved,
    summary="Save the rating card (draft autosave or final revision)",
    description=(
        "`final=false`: overwrites the draft; the shape and size limits are checked (an unset "
        "`change_goal` is fine) and nothing else changes. `final=true`: validates the card "
        "(`change_goal` required), writes a new revision "
        "and sets `rating_submitted`/`has_rating`; `no_rating=true`, or a card with no scores, "
        'counts or notes, is a "no rating" revision (`has_rating=false`). Over 1,000 chars per '
        "reason/note/example or 3,000 for `notes` is 422 `rating_invalid`. Allowed in every state "
        "but `deleting`. A final card may start the first run (R4)."
    ),
)
def put_rating(id: str, body: RatingRequest, request: Request, user: User) -> RatingSaved:
    repo = request.app.state.repo
    uid = user.uid
    _open_session(request, user, id)
    now = datetime.now(UTC)
    if not body.final:
        if issues := validate_rating(body.card, final=False):
            raise _invalid(issues)
        repo.put_rating_draft(uid, id, RatingDraftDoc(card=body.card, updated_at=now))
        return RatingSaved(final=False, updated_at=now)

    if issues := validate_rating(body.card, final=True):
        raise _invalid(issues)
    no_rating = body.no_rating or not has_content(body.card)
    rating_id = uuid4().hex
    repo.put_rating_revision(
        uid,
        id,
        rating_id,
        RatingDoc(
            card=body.card,
            no_rating=no_rating,
            has_rating=not no_rating,
            schema_version=SCHEMA_VERSION,
            created_at=now,
        ),
    )
    fields: dict[str, Any] = {
        "change_goal": body.card["change_goal"],
        "rating_submitted": True,
        "has_rating": not no_rating,
    }
    span = body.card.get("coded_span")
    if isinstance(span, dict) and "from_s" in span and "to_s" in span:
        fields["coded_span"] = {"from_s": span["from_s"], "to_s": span["to_s"]}
    repo.update_session(
        uid,
        id,
        fields,
        status={"rating_submitted": True, "has_rating": not no_rating},
    )
    maybe_start_first_run(
        repo,
        getattr(request.app.state, "queue", None),
        uid,
        id,
        request.app.state.settings,
        getattr(request.state, "request_id", None),
    )
    return RatingSaved(
        final=True, rating_id=rating_id, no_rating=no_rating, has_rating=not no_rating,
        updated_at=now,
    )  # fmt: skip


@router.get(
    "",
    operation_id="getRating",
    response_model=RatingView,
    summary="The latest final revision and, if newer, the autosaved draft",
)
def get_rating(id: str, request: Request, user: User) -> RatingView:
    repo = request.app.state.repo
    _open_session(request, user, id)
    final = repo.latest_rating(user.uid, id)
    draft = repo.get_rating_draft(user.uid, id)
    view = RatingView()
    if final is not None:
        view.final = FinalRating(rating_id=final.id, no_rating=final.no_rating, card=final.card)
    if draft is not None and (final is None or draft.updated_at > final.created_at):
        view.draft = DraftRating(card=draft.card, updated_at=draft.updated_at)
    return view
