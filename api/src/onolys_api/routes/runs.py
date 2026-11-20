"""Runs and reports (PRD R2, R4, D12, D18).

`POST /sessions/{id}/runs` starts a run by hand: a re-run (new report version on the same
transcript, latest final rating, current speaker choice) or the first run when auto-start was held
back by the cap. It reserves a cap slot (429 `daily_cap_reached`), creates the run, moves the
session to `running` (clears the cap error) and enqueues the `run` task; the worker does the rest.
`preset` changes LLM routes only: the transcript and its STT are reused.
"""

import logging
from datetime import datetime
from typing import Annotated, Any
from uuid import uuid4

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, Field

from onolys_api.auth.deps import AuthUser, current_user
from onolys_api.errors import ApiError, ErrorResponse
from onolys_api.jobs import caps
from onolys_api.jobs.machine import advance, invalid_state
from onolys_api.jobs.queue import TaskPayload
from onolys_api.jobs.run import release_once
from onolys_api.presets import UnknownPreset
from onolys_api.repo.base import NotFoundError
from onolys_api.repo.models import RunDoc, SessionDoc, SessionError, SessionState, SttInfo

log = logging.getLogger("onolys_api.runs")
ERRORS = {"default": {"model": ErrorResponse, "description": "Error"}}
router = APIRouter(prefix="/sessions/{id}", tags=["runs"], responses=ERRORS)
runs_router = APIRouter(tags=["runs"], responses=ERRORS)
User = Annotated[AuthUser, Depends(current_user)]
RERUN_STATES = ("awaiting_input", "report_ready", "failed")


class RunRequest(BaseModel):
    n_runs: int | None = Field(None, ge=1, le=5, description="Default: the session's")
    preset: str | None = Field(None, max_length=64, description="Allowlisted; LLM routes only")


class RunSessionRef(BaseModel):
    id: str
    status: SessionState


class RunStarted(BaseModel):
    run_id: str
    session: RunSessionRef


class RunView(BaseModel):
    run_id: str
    session_id: str
    status: str
    stage: str | None = None
    n_runs: int
    preset: str | None = None
    stt: SttInfo | None = None
    rating_id: str | None = None
    code_version: str
    attempts: int
    started: datetime | None = None
    ended: datetime | None = None
    error: str | None = None
    run_info: dict[str, Any] | None = None


class RunList(BaseModel):
    items: list[RunView]


class ReportListItem(BaseModel):
    version: int
    report_id: str
    run_id: str
    created_at: datetime


class ReportList(BaseModel):
    items: list[ReportListItem]


class ReportView(ReportListItem):
    report_schema_version: str
    report: dict[str, Any] = Field(description="The typed report JSON, stored verbatim")


def _view(r: RunDoc) -> RunView:
    return RunView(
        run_id=r.run_id, session_id=r.session_id, status=r.status, stage=r.stage,
        n_runs=r.n_runs, preset=r.preset, stt=r.stt, rating_id=r.rating_id,
        code_version=r.code_version, attempts=r.attempts, started=r.started, ended=r.ended,
        error=r.error, run_info=r.run_info,
    )  # fmt: skip


def _open_session(request: Request, user: AuthUser, id: str) -> SessionDoc:
    s = request.app.state.repo.get_session(user.uid, id)
    if s.state == "deleting":
        raise NotFoundError()
    return s


@router.post(
    "/runs",
    operation_id="startRun",
    status_code=202,
    response_model=RunStarted,
    summary="Start a run by hand (re-run, or the first run held back by the cap)",
    description=(
        "Needs the transcript and the confirmed speaker; uses the latest final rating revision "
        "or runs as no-rating. `preset` changes LLM routes only (the transcript is reused). "
        "Counts against the daily cap: 429 `daily_cap_reached`. 409 `invalid_state` while a run "
        "is in progress or before the inputs exist."
    ),
)
def start_run(id: str, request: Request, user: User, body: RunRequest | None = None) -> RunStarted:
    body = body or RunRequest()
    app = request.app
    repo, uid = app.state.repo, user.uid
    s = _open_session(request, user, id)
    if s.state not in RERUN_STATES or not (
        s.transcript_ready and s.speaker_confirmed and s.clinician_speaker
    ):
        raise invalid_state()
    preset = s.preset
    if body.preset is not None:
        try:
            preset, _ = app.state.presets.resolve(body.preset, s.language)
        except UnknownPreset:
            raise ApiError.of(422, "invalid_parameters", "preset: unknown preset") from None
    settings = app.state.settings
    date = caps.reserve_run(repo, settings, uid)
    run_id = uuid4().hex
    rating = repo.latest_rating(uid, id)
    try:
        repo.create_run(
            uid, id, run_id,
            RunDoc(
                uid=uid, session_id=id, run_id=run_id, n_runs=body.n_runs or s.n_runs,
                preset=preset, rating_id=rating.id if rating else None, stt=s.stt,
                code_version=settings.git_sha, cap_date=date,
            ),
        )  # fmt: skip
        advance(repo, uid, id, to="running", step=None)  # 409 if another call won the race
        if s.first_run_id is None:
            repo.update_session(uid, id, {"first_run_id": run_id})
    except Exception:
        _compensate(repo, uid, id, run_id, date)
        raise
    try:
        queue = getattr(app.state, "queue", None)
        if queue is None:
            raise RuntimeError("no queue")
        queue.enqueue(
            TaskPayload(
                kind="run", uid=uid, sid=id, run_id=run_id,
                request_id=getattr(request.state, "request_id", None),
            )
        )  # fmt: skip
    except Exception as e:
        log.error("run_enqueue_failed session_id=%s run_id=%s exc_class=%s", id, run_id,
                  type(e).__name__)  # fmt: skip
        _compensate(repo, uid, id, run_id, date)
        advance(
            repo, uid, id, to="failed", step=None,
            error=SessionError(code="upstream_unavailable", step="run"),
        )  # fmt: skip
        raise ApiError.of(503, "upstream_unavailable", "Could not start the run.") from None
    return RunStarted(run_id=run_id, session=RunSessionRef(id=id, status="running"))


def _compensate(repo, uid: str, sid: str, run_id: str, date: str) -> None:
    """The run never started: mark it failed and give the slot (and the day's count) back."""
    try:
        repo.update_run(uid, sid, run_id, {"status": "failed", "error": "upstream_unavailable"})
    except NotFoundError:
        pass
    release_once(repo, uid, sid, run_id, True, date)


@router.get(
    "/runs",
    operation_id="listRuns",
    response_model=RunList,
    summary="The session's runs, oldest first",
)
def list_runs(id: str, request: Request, user: User) -> RunList:
    _open_session(request, user, id)
    return RunList(items=[_view(r) for r in request.app.state.repo.list_runs(user.uid, id)])


@runs_router.get(
    "/runs/{run_id}",
    operation_id="getRun",
    response_model=RunView,
    summary="One run: status, params, run_info",
)
def get_run(run_id: str, request: Request, user: User) -> RunView:
    repo = request.app.state.repo
    run = repo.get_run_by_id(user.uid, run_id)
    _open_session(request, user, run.session_id)
    return _view(run)


@router.get(
    "/reports",
    operation_id="listReports",
    response_model=ReportList,
    summary="Report versions, oldest first",
)
def list_reports(id: str, request: Request, user: User) -> ReportList:
    _open_session(request, user, id)
    docs = request.app.state.repo.list_reports(user.uid, id)
    return ReportList(
        items=[
            ReportListItem(version=d.version, report_id=d.id, run_id=d.run_id,
                           created_at=d.created_at)
            for d in docs
        ]
    )  # fmt: skip


@router.get(
    "/reports/{version}",
    operation_id="getReport",
    response_model=ReportView,
    summary="One report by integer version (the public report address)",
    description="`Cache-Control: private, no-store`: the report carries PHI.",
)
def get_report(id: str, version: int, request: Request, response: Response, user: User):
    _open_session(request, user, id)
    d = request.app.state.repo.get_report_by_version(user.uid, id, version)
    response.headers["Cache-Control"] = "private, no-store"
    assert d.report is not None
    return ReportView(
        version=d.version, report_id=d.id, run_id=d.run_id, created_at=d.created_at,
        report_schema_version=d.report_schema_version, report=d.report,
    )  # fmt: skip
