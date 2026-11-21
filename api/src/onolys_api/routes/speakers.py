"""`/v1/sessions/{id}/speakers`, `.../speakers/confirm`, `.../transcript` (R2, R4, D13).

The speaker gate is the last human input. `confirm` sets `speaker_confirmed` and the clinician's
speaker label (every other speaker counts as client) and calls the first-run gate. In
`report_ready|failed` it only changes the choice for the NEXT run; reports are never touched.
The transcript read is owner-scoped and `private, no-store`: it carries PHI.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, Field

from onolys_api.auth.deps import AuthUser, current_user
from onolys_api.errors import ApiError, ErrorResponse
from onolys_api.jobs.first_run import maybe_start_first_run
from onolys_api.jobs.machine import invalid_state
from onolys_api.jobs.transcribe import TRANSCRIPT_ID
from onolys_api.repo.base import NotFoundError
from onolys_api.repo.models import SessionDoc, SessionState

SAMPLES_PER_SPEAKER = 3
SAMPLE_MAX_CHARS = 300
CONFIRM_STATES = ("awaiting_input", "report_ready", "failed")

ERRORS = {"default": {"model": ErrorResponse, "description": "Error"}}
router = APIRouter(prefix="/sessions/{id}", tags=["speakers"], responses=ERRORS)
User = Annotated[AuthUser, Depends(current_user)]


class SpeakerInfo(BaseModel):
    speaker: str
    turn_count: int
    samples: list[str] = Field(description="Up to 3 of the speaker's first lines")


class SpeakersView(BaseModel):
    speakers: list[SpeakerInfo]
    clinician_speaker: str | None = None


class ConfirmRequest(BaseModel):
    clinician_speaker: str = Field(min_length=1, max_length=200)


class ConfirmSessionRef(BaseModel):
    id: str
    status: SessionState


class ConfirmResponse(BaseModel):
    session: ConfirmSessionRef
    clinician_speaker: str


class TranscriptTurn(BaseModel):
    id: str
    speaker: str | None = None
    role: str | None = Field(None, description="`clinician`/`client`; null until confirmed")
    start_ms: int | None = None
    end_ms: int | None = None
    text: str


class TranscriptView(BaseModel):
    turns: list[TranscriptTurn]
    language: str | None = None
    duration_ms: int | None = None
    clinician_speaker: str | None = None


def _ready_session(request: Request, user: AuthUser, id: str) -> SessionDoc:
    s = request.app.state.repo.get_session(user.uid, id)
    if s.state == "deleting":
        raise NotFoundError()
    if not s.transcript_ready:
        raise invalid_state()
    return s


def _speakers(transcript) -> list[SpeakerInfo]:
    out: dict[str, SpeakerInfo] = {}
    for t in transcript.turns:
        if t.speaker is None:
            continue
        info = out.setdefault(t.speaker, SpeakerInfo(speaker=t.speaker, turn_count=0, samples=[]))
        info.turn_count += 1
        if len(info.samples) < SAMPLES_PER_SPEAKER:
            info.samples.append(t.text[:SAMPLE_MAX_CHARS])
    return list(out.values())


@router.get(
    "/speakers",
    operation_id="getSpeakers",
    response_model=SpeakersView,
    summary="Speakers with sample lines, for picking the clinician",
    description=(
        "Every speaker in first-appearance order, each with up to 3 sample lines. 409 "
        "`invalid_state` until the transcript is ready."
    ),
)
def get_speakers(id: str, request: Request, user: User) -> SpeakersView:
    s = _ready_session(request, user, id)
    tdoc = request.app.state.repo.get_transcript(user.uid, id, TRANSCRIPT_ID)
    assert tdoc.transcript is not None
    return SpeakersView(speakers=_speakers(tdoc.transcript), clinician_speaker=s.clinician_speaker)


@router.post(
    "/speakers/confirm",
    operation_id="confirmSpeakers",
    status_code=202,
    response_model=ConfirmResponse,
    summary="Pick the clinician speaker (every other speaker is the client)",
    description=(
        "Allowed once the transcript is ready and not while a run is in progress. In "
        "`report_ready|failed` it applies to the next run only. May start the first run (R4)."
    ),
)
def confirm_speakers(
    id: str, body: ConfirmRequest, request: Request, user: User
) -> ConfirmResponse:
    repo = request.app.state.repo
    s = _ready_session(request, user, id)
    if s.state not in CONFIRM_STATES:
        raise invalid_state()
    tdoc = repo.get_transcript(user.uid, id, TRANSCRIPT_ID)
    assert tdoc.transcript is not None
    if body.clinician_speaker not in {i.speaker for i in _speakers(tdoc.transcript)}:
        raise ApiError.of(422, "invalid_parameters", "clinician_speaker: unknown speaker")
    repo.update_session(
        user.uid,
        id,
        {"clinician_speaker": body.clinician_speaker, "speaker_confirmed": True},
        status={"speaker_confirmed": True},
    )
    maybe_start_first_run(
        repo,
        getattr(request.app.state, "queue", None),
        user.uid,
        id,
        request.app.state.settings,
        getattr(request.state, "request_id", None),
    )
    status = repo.get_session(user.uid, id).state
    return ConfirmResponse(
        session=ConfirmSessionRef(id=id, status=status), clinician_speaker=body.clinician_speaker
    )


@router.get(
    "/transcript",
    operation_id="getTranscript",
    response_model=TranscriptView,
    summary="The transcript, with roles once the clinician is confirmed",
    description=(
        "Owner-scoped; `Cache-Control: private, no-store`. Report offsets are code points into "
        "`turn.text`. 409 `invalid_state` before transcription finishes."
    ),
)
def get_transcript(id: str, request: Request, response: Response, user: User) -> TranscriptView:
    s = _ready_session(request, user, id)
    tdoc = request.app.state.repo.get_transcript(user.uid, id, TRANSCRIPT_ID)
    assert tdoc.transcript is not None
    t = tdoc.transcript
    who = s.clinician_speaker if s.speaker_confirmed else None
    response.headers["Cache-Control"] = "private, no-store"
    return TranscriptView(
        turns=[
            TranscriptTurn(
                id=x.id,
                speaker=x.speaker,
                role=(
                    None
                    if who is None or x.speaker is None
                    else "clinician"
                    if x.speaker == who
                    else "client"
                ),
                start_ms=x.start_ms,
                end_ms=x.end_ms,
                text=x.text,
            )
            for x in t.turns
        ],
        language=t.language,
        duration_ms=t.duration_ms,
        clinician_speaker=who,
    )
