"""Job state machine core (PRD R4, D13): states, allowed transitions, flags, progress table.

`advance` is the single status-mirror helper: every state/step/progress/flag/error change goes
through it, and it writes `sessions/{sid}` and `session_status/{sid}` in one repo call. The
status document carries no text (R7, AC11).

Not transactional: callers that race (the first-run gate, Task 7) add their own transaction.
"""

from typing import Any, get_args

from onolys_api.errors import ApiError
from onolys_api.repo.base import Repo
from onolys_api.repo.models import SessionError, SessionState

STATES: tuple[str, ...] = get_args(SessionState)

_NOT_DELETING = (
    "created", "uploading", "validating", "transcribing", "awaiting_input",
    "running", "report_ready", "failed",
)  # fmt: skip

TRANSITIONS: dict[str, frozenset[str]] = {
    "created": frozenset({"uploading", "deleting"}),
    # uploading -> uploading: a fresh signed URL for the same session
    "uploading": frozenset({"uploading", "validating", "deleting"}),
    "validating": frozenset({"transcribing", "failed", "deleting"}),
    "transcribing": frozenset({"awaiting_input", "failed", "deleting"}),
    "awaiting_input": frozenset({"running", "deleting"}),
    "running": frozenset({"report_ready", "failed", "deleting"}),
    "report_ready": frozenset({"running", "deleting"}),  # re-run
    "failed": frozenset({"running", "deleting"}),  # re-run
    "deleting": frozenset(),
}
assert set(TRANSITIONS) == set(STATES) and all("deleting" in TRANSITIONS[s] for s in _NOT_DELETING)

FLAGS = ("transcript_ready", "speaker_confirmed", "rating_submitted", "has_rating")

# R4 progress table
STATE_PROGRESS: dict[str, int] = {
    "created": 0,
    "uploading": 5,
    "validating": 10,
    "transcribing": 20,
    "awaiting_input": 40,
    "running": 45,
    "report_ready": 100,
}
RUN_START_PROGRESS = STATE_PROGRESS["running"]
STAGE_WEIGHTS: dict[str, int] = {"paudit": 25, "eaudit": 15, "tips": 8, "compare": 4, "assemble": 3}
STAGES = tuple(STAGE_WEIGHTS)

# fields of session_status/{sid} (everything the web may read; no text)
STATUS_FIELDS = frozenset(
    {
        "uid", "state", "step", "progress", "error_code", "latest_report_version", "updated_at",
        *FLAGS,
    }
)  # fmt: skip

_KEEP: Any = object()


def invalid_state() -> ApiError:
    return ApiError.of(409, "invalid_state", "The session is not in a state that allows this.")


def check_transition(current: str, to: str) -> None:
    if to not in TRANSITIONS.get(current, frozenset()):
        raise invalid_state()


def next_progress(current: int, to: str) -> int:
    """Progress after entering `to`. Never decreases, except a re-run restarting at 45 (see
    `advance`); `failed`/`deleting` keep the last value."""
    return max(current, STATE_PROGRESS.get(to, current))


def stage_progress(current: int, stage: str) -> int:
    """Add a finished stage's weight. Capped at 99: 100 belongs to `report_ready`."""
    if stage not in STAGE_WEIGHTS:
        raise ValueError(f"unknown stage {stage!r}")
    return min(99, current + STAGE_WEIGHTS[stage])


def advance(
    repo: Repo,
    uid: str,
    sid: str,
    *,
    to: str | None = None,
    step: Any = _KEEP,
    error: SessionError | None | Any = _KEEP,
    flags: dict[str, bool] | None = None,
    stage_done: str | None = None,
    latest_report_version: int | None | Any = _KEEP,
) -> None:
    """Apply one change to the session and mirror it to `session_status` in the same write.

    `to`: validated against TRANSITIONS (409 invalid_state). `step`: the stage label.
    `error`: the error (session.error + status.error_code); entering a non-failed state clears
    it unless given; `failed` requires one. `stage_done`: a stage finished or failed, adds its
    weight. Raises NotFoundError for another user's session.
    """
    session = repo.get_session(uid, sid)
    status = repo.get_status(uid, sid)
    if to is not None:
        check_transition(session.state, to)
        if to == "failed" and (error is _KEEP or error is None):
            raise ValueError("a failed session needs an error")
    if flags and not set(flags) <= set(FLAGS):
        raise ValueError("unknown flag")

    new_state = to or session.state
    progress = status.progress
    if to == "running" and session.state in ("report_ready", "failed"):
        progress = RUN_START_PROGRESS  # a re-run restarts
    elif to is not None:
        progress = next_progress(progress, to)
    if stage_done is not None:
        progress = stage_progress(progress, stage_done)

    if error is _KEEP and to is not None and to != "failed":
        error = None
    s_fields: dict[str, Any] = {"state": new_state}
    st_fields: dict[str, Any] = {"state": new_state, "progress": progress}
    if step is not _KEEP:
        s_fields["step"] = step
        st_fields["step"] = step
    if error is not _KEEP:
        s_fields["error"] = error.model_dump() if error else None
        st_fields["error_code"] = error.code if error else None
    if latest_report_version is not _KEEP:
        s_fields["latest_report_version"] = latest_report_version
        st_fields["latest_report_version"] = latest_report_version
    for k, v in (flags or {}).items():
        s_fields[k] = v
        st_fields[k] = v
    repo.update_session(uid, sid, s_fields, status=st_fields)
