"""Hard delete and its cleanup task (PRD R7 Delete, AC8).

`delete_session_data` is the one routine, run inline by `DELETE /sessions/{id}` and again by the
`delete` task when the inline attempt failed. Every step is safe to repeat:

1. mark the session `deleting` (blocks reads and new runs; a no-op when already marked);
2. release the cap slot of every run that still holds one (queued or running), exactly once, via
   the run's `released` flag. The run task never releases a slot for a session that no longer
   exists, so this is the single owner. Usage counters (`usage/*`, `users/*`) are per user and
   stay;
3. list-and-delete every object under `{uid}/{sid}/` and `uploads/{uid}/{sid}/`, then verify both
   prefixes are empty (else raise: the session stays `deleting`);
4. recursive delete of the session doc, its subcollections and `session_status/{sid}`;
5. one content-free `session_deleted` log line, only by the call that removed the document, so
   retries and duplicate tasks never add a second line. No tombstone is kept.

Not handled in v1 (deferred in the PRD): an in-flight run may still write after the delete.
"""

import logging

from onolys_api import logs
from onolys_api.jobs.machine import advance
from onolys_api.jobs.run import release_once
from onolys_api.jobs.worker import Handler, RetryableError, TaskContext, TaskError
from onolys_api.repo.base import NotFoundError, Repo
from onolys_api.storage.base import BlobStore


class DeleteIncomplete(Exception):
    """Objects were still listed after the delete (or storage/Firestore raised)."""


def session_prefixes(uid: str, sid: str) -> tuple[str, str]:
    return f"{uid}/{sid}/", f"uploads/{uid}/{sid}/"


def _release_run_slots(repo: Repo, uid: str, sid: str) -> None:
    for run in repo.list_runs(uid, sid):
        if run.released or run.status not in ("pending", "running"):
            continue  # finished runs already gave their slot back
        # a run that never started (no attempt) has not called the LLM: refund its daily count
        never_started = run.status == "pending" and run.attempts == 0
        release_once(repo, uid, sid, run.run_id, never_started, run.cap_date)


def delete_session_data(
    repo: Repo, blobs: BlobStore, uid: str, sid: str, request_id: str | None = None
) -> bool:
    """Delete everything of one session. True when this call removed the session document."""
    try:
        session = repo.get_session(uid, sid)
    except NotFoundError:
        session = None  # an earlier attempt already removed it: only storage may be left
    if session is not None:
        if session.state != "deleting":
            advance(repo, uid, sid, to="deleting")
        _release_run_slots(repo, uid, sid)

    prefixes = session_prefixes(uid, sid)
    for prefix in prefixes:
        blobs.delete_prefix(prefix)
    if any(blobs.list_keys(prefix) for prefix in prefixes):
        raise DeleteIncomplete()

    removed = repo.delete_session(uid, sid)
    if removed:
        logs.emit(
            "session_deleted", session_id=sid, uid_hash=logs.uid_hash(uid), request_id=request_id
        )
    return removed


def make_delete_handler(blobs: BlobStore) -> Handler:
    """Register with `HandlerSpec(fn, claim=False)`: no step record, the session may be gone."""

    def delete(ctx: TaskContext) -> None:
        try:
            delete_session_data(ctx.repo, blobs, ctx.uid, ctx.sid, ctx.request_id)
        except TaskError:
            raise
        except Exception as e:
            logs.emit(
                "session_delete_failed", logging.WARNING, session_id=ctx.sid,
                exc_class=type(e).__name__, request_id=ctx.request_id,
            )  # fmt: skip
            raise RetryableError("upstream_unavailable") from None

    return delete
