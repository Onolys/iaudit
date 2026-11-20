"""First-run gate (PRD R4, D13): `maybe_start_first_run`.

Called after each of the three inputs lands (transcribe completion, speaker confirm, final
rating). Each caller sets its own flag first and then calls this, so the last caller always sees
all three flags. The decision is one repo transaction (`Repo.start_first_run`): flags +
`first_run_id` absent + cap check + run creation + `state=running` commit together, so exactly one
caller wins. The cap reservation (runs+1, active_runs+1) lives in that same transaction: if the
transaction loses the race or is refused, nothing was reserved and there is nothing to compensate.
The `run` task is enqueued only after commit, under the name `{run_id}-run` (duplicates are
no-ops). If that enqueue fails, the committed run is failed and its slot refunded (compensation).
"""

import logging
from uuid import uuid4

from onolys_api.config import Settings
from onolys_api.jobs import caps
from onolys_api.jobs.machine import RUN_START_PROGRESS, advance
from onolys_api.jobs.queue import TaskPayload, TaskQueue
from onolys_api.repo.base import Repo
from onolys_api.repo.models import SessionError

log = logging.getLogger("onolys_api.first_run")


def maybe_start_first_run(
    repo: Repo, queue: TaskQueue | None, uid: str, sid: str, settings: Settings,
    request_id: str | None = None,
) -> None:  # fmt: skip
    if queue is None:  # nowhere to send the `run` task: leave the session as it is
        log.error("first_run_no_queue session_id=%s", sid)
        return
    run_id = uuid4().hex
    date = caps.utc_date()
    outcome = repo.start_first_run(
        uid, sid, run_id, date, settings.daily_run_cap, settings.max_active_runs,
        settings.git_sha, RUN_START_PROGRESS,
    )  # fmt: skip
    if outcome != "started":
        if outcome in ("daily_cap", "concurrent"):
            log.info("first_run_held session_id=%s error_code=daily_cap_reached", sid)
        return
    try:
        queue.enqueue(
            TaskPayload(kind="run", uid=uid, sid=sid, run_id=run_id, request_id=request_id)
        )
    except Exception as e:
        log.error(
            "first_run_enqueue_failed session_id=%s run_id=%s exc_class=%s",
            sid, run_id, type(e).__name__,
        )  # fmt: skip
        repo.update_run(uid, sid, run_id, {"status": "failed", "error": "upstream_unavailable"})
        caps.release_run(repo, uid, date, refund=True)
        advance(
            repo, uid, sid, to="failed", step=None,
            error=SessionError(code="upstream_unavailable", step="run"),
        )  # fmt: skip
