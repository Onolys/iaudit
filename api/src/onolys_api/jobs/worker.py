"""Handler wrapper for queue tasks (PRD R5, D3). One retry rule, no app-level retry loop.

Per delivery: claim the step/run record (lease = deadline + 60 s), run the handler, then
- success: record `done` (unless the handler finishes the step itself: `complete=False`);
- PermanentError / unexpected exception: record `failed` + error code, answer 2xx (no retry);
- RetryableError / TimeoutError: if another attempt is left (X-CloudTasks-TaskRetryCount + 1 <
  MAX_ATTEMPTS) release the claim and answer 503 so Cloud Tasks retries; on the last attempt
  record `failed` and answer 2xx.
Duplicate deliveries find `done`/`failed` and do nothing; a live lease answers 503 (2xx on the
last attempt). Every session transition goes through `advance`, which mirrors session_status.
Logs carry codes and ids only, never text.
"""

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal

from onolys_api.errors import ApiError
from onolys_api.jobs.machine import advance
from onolys_api.jobs.queue import MAX_ATTEMPTS, TaskPayload, TaskQueue
from onolys_api.repo.base import NotFoundError, Repo
from onolys_api.repo.models import SessionError

log = logging.getLogger("onolys_api.worker")

DEADLINE_S = 8 * 60  # internal deadline (RunContext.deadline) for validate and run
LEASE_GRACE_S = 60  # lease = deadline + 60 s
RETRYABLE_CODES = ("upstream_unavailable", "deadline_exceeded", "rate_limited")


class TaskError(Exception):
    retryable = False

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class PermanentError(TaskError):
    """Record `failed` with this public error code; Cloud Tasks gets 2xx."""


class RetryableError(TaskError):
    """upstream_unavailable, timeout, 429: 5xx while an attempt is left."""

    retryable = True


@dataclass
class TaskContext:
    payload: TaskPayload
    repo: Repo
    queue: TaskQueue
    attempt: int  # 1-based
    deadline: datetime
    clock: Callable[[], datetime]

    @property
    def uid(self) -> str:
        return self.payload.uid

    @property
    def sid(self) -> str:
        return self.payload.sid

    @property
    def request_id(self) -> str | None:
        return self.payload.request_id

    def remaining_s(self) -> float:
        return (self.deadline - self.clock()).total_seconds()

    def check_deadline(self) -> None:
        if self.remaining_s() <= 0:
            raise RetryableError("deadline_exceeded")

    def enqueue(self, payload: TaskPayload, delay_s: float = 0.0) -> None:
        """Enqueue a follow-up task, carrying this task's request id."""
        if payload.request_id is None:
            payload = payload.model_copy(update={"request_id": self.request_id})
        self.queue.enqueue(payload, delay_s)


Handler = Callable[[TaskContext], None]


@dataclass(frozen=True)
class HandlerSpec:
    fn: Handler
    step: str | None = None  # step record name (scope "step"); also the session `step` label
    scope: Literal["step", "run"] = "step"
    claim: bool = True  # False: no claim (a poll, whose step record is owned by its transcribe)
    complete: bool = True  # False: the handler (or a later task) marks the step done itself


@dataclass(frozen=True)
class TaskResult:
    status_code: int
    outcome: str  # done | duplicate | busy | retry | failed | gone | skipped


class TaskRunner:
    def __init__(
        self,
        repo: Repo,
        queue: TaskQueue,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self.repo = repo
        self.queue = queue
        self.clock = clock
        self._registry: dict[str, HandlerSpec] = {}
        self._deadline_s: float = DEADLINE_S
        if hasattr(queue, "bind"):
            queue.bind(lambda p, retry: self.handle(p, retry).status_code)

    def register(self, kind: str, spec: HandlerSpec) -> None:
        self._registry[kind] = spec

    def has(self, kind: str) -> bool:
        return kind in self._registry

    # ---- delivery ----

    def handle(self, payload: TaskPayload, retry_count: int = 0) -> TaskResult:
        spec = self._registry.get(payload.kind)
        if spec is None:
            log.error("no_handler kind=%s request_id=%s", payload.kind, payload.request_id)
            return TaskResult(200, "skipped")  # nothing a retry could fix
        attempt = retry_count + 1
        last = attempt >= MAX_ATTEMPTS
        now = self.clock()
        lease_s = self._deadline_s + LEASE_GRACE_S
        try:
            if spec.claim:
                claim = self._claim(spec, payload, now, lease_s)
                if claim.outcome in ("done", "failed"):
                    return TaskResult(200, "duplicate")
                if claim.outcome == "busy":
                    return TaskResult(200 if last else 503, "busy")
                attempt = max(attempt, claim.attempts)
            ctx = TaskContext(
                payload, self.repo, self.queue, attempt,
                now + timedelta(seconds=self._deadline_s), self.clock,
            )  # fmt: skip
            try:
                spec.fn(ctx)
            except TimeoutError:
                raise RetryableError("deadline_exceeded") from None
            if spec.claim and spec.complete:
                self._mark_done(spec, payload)
            return TaskResult(200, "done")
        except NotFoundError:
            return TaskResult(200, "gone")  # session deleted: nothing left to do
        except TaskError as e:
            return self._on_error(spec, payload, e, last)
        except Exception as e:
            log.error(
                "handler_exception kind=%s exc_class=%s request_id=%s",
                payload.kind, type(e).__name__, payload.request_id,
            )  # fmt: skip
            return self._on_error(spec, payload, PermanentError("internal_error"), last)

    # ---- records ----

    def _claim(self, spec: HandlerSpec, p: TaskPayload, now: datetime, lease_s: float):
        if spec.scope == "run":
            if not p.run_id:
                raise PermanentError("internal_error")
            return self.repo.claim_run(p.uid, p.sid, p.run_id, now, lease_s)
        assert spec.step
        return self.repo.claim_step(p.uid, p.sid, spec.step, now, lease_s)

    def _record(self, spec: HandlerSpec, p: TaskPayload, **fields) -> None:
        if spec.scope == "run":
            if p.run_id:
                self.repo.update_run(p.uid, p.sid, p.run_id, fields)
        elif spec.step:
            self.repo.update_session(
                p.uid, p.sid, {f"steps.{spec.step}.{k}": v for k, v in fields.items()}
            )

    def _mark_done(self, spec: HandlerSpec, p: TaskPayload) -> None:
        self._record(spec, p, status="done", ended=self.clock(), error=None)

    def _on_error(self, spec: HandlerSpec, p: TaskPayload, e: TaskError, last: bool) -> TaskResult:
        if e.retryable and not last:
            if spec.claim:  # release so the retry can claim it again
                self._safe(self._record, spec, p, status="pending", error=e.code)
            log.warning("task_retry kind=%s code=%s request_id=%s", p.kind, e.code, p.request_id)
            return TaskResult(503, "retry")
        self._fail(spec, p, e.code)
        return TaskResult(200, "failed")

    def _fail(self, spec: HandlerSpec, p: TaskPayload, code: str) -> None:
        log.warning("task_failed kind=%s code=%s request_id=%s", p.kind, code, p.request_id)
        self._safe(self._record, spec, p, status="failed", ended=self.clock(), error=code)
        label = spec.step or "run"
        self._safe(
            advance, self.repo, p.uid, p.sid, to="failed", step=label,
            error=SessionError(code=code, step=label),
        )  # fmt: skip

    @staticmethod
    def _safe(fn, *args, **kw) -> None:
        """Bookkeeping must never turn a handled outcome into a 5xx (and a retry)."""
        try:
            fn(*args, **kw)
        except (ApiError, NotFoundError):
            pass  # e.g. session deleted or already failed: the transition is not allowed
        except Exception as e:
            log.error("bookkeeping_failed exc_class=%s", type(e).__name__)
