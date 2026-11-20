"""The `run` task (PRD R4 Run, R5, R6, D2, D12, D17): the whole evaluation as one task.

The handler calls the `Evaluation` adapter in-process. `progress_cb(stage, status)` writes
`session_status.step` (the stage last `started`) and adds a finished stage's weight to `progress`
(a failed stage counts too); the value is `45 + sum(weights of finished stages)`, capped at 99 and
never lower than what is already shown, so a retry (which re-runs everything) stays flat until it
catches up. 100 belongs to `report_ready`.

Outcome: the report is validated against the report schema, stored verbatim (the repo moves it to
GCS above 500 KB) under a deterministic report id (= run id), the run artifacts go to
`{uid}/{sid}/runs/{run_id}/{paudit,eaudit,tips}.json`, and the session moves to `report_ready`
with the new `latest_report_version`. A paudit failure fails the run and the session; eaudit/tips
failures arrive as report warnings and still ship (the adapter handles them). A redelivered or
retried task finds the stored report and only finishes the bookkeeping: one report per run.

Cap slot: every run is released exactly once (`released` flag on the run record), when the run
ends for good: success or failure (`refund=True` only if it failed before the evaluation was
called), but not on a retryable failure with an attempt left.
"""

import json
import logging
import time
from collections.abc import Callable
from functools import lru_cache
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator
from onolys_core.engine import RunContext

from onolys_api import logs
from onolys_api.adapters.base import AdapterError, Evaluation
from onolys_api.jobs import caps
from onolys_api.jobs.machine import RUN_START_PROGRESS, STAGE_WEIGHTS, advance
from onolys_api.jobs.queue import MAX_ATTEMPTS
from onolys_api.jobs.transcribe import TRANSCRIPT_ID
from onolys_api.jobs.transcribe import _run as run_coro
from onolys_api.jobs.worker import (
    RETRYABLE_CODES,
    Handler,
    PermanentError,
    RetryableError,
    TaskContext,
    TaskError,
)
from onolys_api.repo.base import NotFoundError
from onolys_api.repo.models import ReportDoc
from onolys_api.storage.base import BlobStore

REAL_REPORT_SCHEMA = (
    Path(__file__).resolve().parents[4] / "engines/evaluation/schemas/report.schema.json"
)
LOCAL_REPORT_SCHEMA = Path(__file__).resolve().parents[1] / "schemas/report.local.schema.json"
ARTIFACTS = ("paudit", "eaudit", "tips")
MAX_PROGRESS = 99


@lru_cache(maxsize=1)
def report_validator() -> Draft202012Validator:
    """SP03 `report.schema.json` once it exists in the checkout, else the bundled stand-in."""
    path = REAL_REPORT_SCHEMA if REAL_REPORT_SCHEMA.exists() else LOCAL_REPORT_SCHEMA
    return Draft202012Validator(json.loads(path.read_text()))


def artifact_key(uid: str, sid: str, run_id: str, name: str) -> str:
    return f"{uid}/{sid}/runs/{run_id}/{name}.json"


def _dumps(obj: Any) -> bytes:
    return json.dumps(obj, ensure_ascii=False, default=str).encode()


def release_once(repo, uid: str, sid: str, run_id: str, refund: bool, date: str | None) -> None:
    """Hand the cap slot back at most once per run (flag first: never twice)."""
    try:
        run = repo.get_run(uid, sid, run_id)
        if run.released:
            return
        date = run.cap_date or date
        repo.update_run(uid, sid, run_id, {"released": True})
    except NotFoundError:  # session deleted under the run: the delete already freed the slot
        return
    if date:
        caps.release_run(repo, uid, date, refund)


def make_run_handler(
    blobs: BlobStore, get_evaluation: Callable[[], Evaluation], settings=None
) -> Handler:
    """Register with `HandlerSpec(fn, scope="run")` (claim on the run record)."""

    def run(ctx: TaskContext) -> None:
        uid, sid, run_id = ctx.uid, ctx.sid, ctx.payload.run_id
        assert run_id
        repo = ctx.repo
        started = {"llm": False}
        run_doc = repo.get_run(uid, sid, run_id)
        date = run_doc.cap_date
        try:
            _execute(ctx, blobs, get_evaluation(), run_doc, started)
        except (TaskError, TimeoutError) as e:
            retryable = isinstance(e, TimeoutError) or e.retryable
            if not retryable or ctx.attempt >= MAX_ATTEMPTS:
                release_once(repo, uid, sid, run_id, not started["llm"], date)
            raise
        except Exception:
            release_once(repo, uid, sid, run_id, not started["llm"], date)
            raise
        release_once(repo, uid, sid, run_id, False, date)

    return run


def _execute(ctx, blobs, evaluation, run_doc, started: dict[str, bool]) -> None:
    uid, sid, run_id, repo = ctx.uid, ctx.sid, run_doc.run_id, ctx.repo
    session = repo.get_session(uid, sid)
    if session.state == "deleting":
        raise NotFoundError()

    try:  # a retry or redelivery after the report was stored only finishes the bookkeeping
        existing = repo.get_report(uid, sid, run_id, resolve=False)
    except NotFoundError:
        existing = None
    if existing is None:
        existing = _evaluate(ctx, blobs, evaluation, run_doc, session, started)

    repo.update_run(uid, sid, run_id, {"stage": None})
    if repo.get_session(uid, sid).state != "report_ready":
        advance(
            repo, uid, sid, to="report_ready", step=None,
            latest_report_version=existing.version,
        )  # fmt: skip


def _evaluate(ctx, blobs, evaluation, run_doc, session, started) -> ReportDoc:
    uid, sid, run_id, repo = ctx.uid, ctx.sid, run_doc.run_id, ctx.repo
    if session.clinician_speaker is None:
        raise PermanentError("internal_error")
    transcript = repo.get_transcript(uid, sid, TRANSCRIPT_ID).transcript
    if transcript is None:
        raise PermanentError("internal_error")
    rating_card = None
    if run_doc.rating_id:
        rating = repo.get_rating(uid, sid, run_doc.rating_id)
        rating_card = rating.card if rating.has_rating and not rating.no_rating else None
    params = {
        "change_goal": session.change_goal or "",
        "coded_span": session.coded_span.model_dump() if session.coded_span else None,
        "language": transcript.language or session.language,
        "n_runs": run_doc.n_runs,
        "preset": run_doc.preset,
        "code_version": run_doc.code_version,
        "stub_title": session.title or "",  # real adapters ignore it
    }
    done: set[str] = set()

    def progress_cb(stage: str, status: str) -> None:
        if stage not in STAGE_WEIGHTS:
            return
        try:
            if status == "started":
                repo.update_session(uid, sid, {"step": stage}, status={"step": stage})
            elif stage not in done:
                done.add(stage)
                total = RUN_START_PROGRESS + sum(STAGE_WEIGHTS[s] for s in done)
                shown = repo.get_status(uid, sid).progress
                repo.update_session(
                    uid, sid, {}, status={"progress": max(shown, min(MAX_PROGRESS, total))}
                )
        except NotFoundError:
            raise
        except Exception as e:  # progress is best effort: never fail the run for it
            logs.emit(
                "progress_write_failed",
                logging.WARNING,
                session_id=sid,
                run_id=run_id,
                exc_class=type(e).__name__,
            )

    rctx = RunContext(
        llm=None, metrics=None, request_id=ctx.request_id or "",
        deadline=time.monotonic() + max(0.0, ctx.remaining_s()),
    )  # fmt: skip
    started["llm"] = True
    try:
        out = run_coro(
            evaluation.run(
                rctx, None, transcript, {"subject": session.clinician_speaker}, params,
                rating_card, progress_cb,
            )
        )  # fmt: skip
    except AdapterError as e:
        if e.code in RETRYABLE_CODES:
            raise RetryableError(e.code) from None
        raise PermanentError("internal_error") from None  # engine -> public code map: SP09

    if any(True for _ in report_validator().iter_errors(out.report)):
        logs.emit("report_schema_invalid", logging.ERROR, session_id=sid, run_id=run_id)
        raise PermanentError("internal_error")

    prefix = f"{uid}/{sid}/runs/{run_id}/"
    for name in ARTIFACTS:
        if out.artifacts.get(name) is not None:
            blobs.put_bytes(artifact_key(uid, sid, run_id, name), _dumps(out.artifacts[name]),
                            "application/json")  # fmt: skip
    versions = [r.version for r in repo.list_reports(uid, sid)]
    doc = ReportDoc(
        version=max(versions, default=0) + 1,
        run_id=run_id,
        report=out.report,
        report_schema_version=str(out.report.get("schema_version", "")),
    )
    repo.put_report(uid, sid, run_id, doc)
    repo.update_run(
        uid, sid, run_id,
        {"run_info": out.report.get("run_info"), "artifacts_prefix": blobs.uri(prefix)},
    )  # fmt: skip
    return doc
