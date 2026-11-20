"""Task queue (R5): Cloud Tasks in the cloud, an in-memory queue for SERVICE_MODE=combined.

Task names make enqueue idempotent inside Cloud Tasks' dedup window: `{sid}-validate`,
`{sid}-transcribe`, `{sid}-poll-{n}`, `{run_id}-run`, `{sid}-delete`. The payload carries the
request id (never any text). `enqueue` is sync: routes and handlers run in threadpool workers.
"""

import threading
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Literal, Protocol

from pydantic import BaseModel

from onolys_api import logs
from onolys_api.config import Settings

TaskKind = Literal["validate", "transcribe", "transcribe-poll", "run", "delete"]
KINDS: tuple[str, ...] = ("validate", "transcribe", "transcribe-poll", "run", "delete")
MAX_ATTEMPTS = 2  # the Cloud Tasks queue's max_attempts: the one automatic retry (D3)
DISPATCH_DEADLINE_S = 600


class TaskPayload(BaseModel):
    kind: TaskKind
    uid: str
    sid: str
    run_id: str | None = None
    n: int | None = None  # poll sequence number
    request_id: str | None = None


def task_name(p: TaskPayload) -> str:
    if p.kind == "run":
        if not p.run_id:
            raise ValueError("run task needs run_id")
        return f"{p.run_id}-run"
    if p.kind == "transcribe-poll":
        if p.n is None:
            raise ValueError("poll task needs n")
        return f"{p.sid}-poll-{p.n}"
    return f"{p.sid}-{p.kind}"


class TaskQueue(Protocol):
    def enqueue(self, payload: TaskPayload, delay_s: float = 0.0) -> None: ...


class CloudTasksQueue:
    """Cloud Tasks HTTP target with an OIDC token (audience = worker URL, SA = tasks-invoker).
    The client is created lazily so building the app needs no credentials."""

    def __init__(self, settings: Settings, client=None) -> None:
        self._s = settings
        self._client = client

    def _get_client(self):
        if self._client is None:
            from google.cloud import tasks_v2

            self._client = tasks_v2.CloudTasksClient()
        return self._client

    def enqueue(self, payload: TaskPayload, delay_s: float = 0.0) -> None:
        from google.api_core.exceptions import AlreadyExists
        from google.protobuf import duration_pb2, timestamp_pb2

        s, client = self._s, self._get_client()
        parent = (
            s.tasks_queue
            if "/" in s.tasks_queue
            else client.queue_path(s.gcp_project, s.region, s.tasks_queue)
        )
        task: dict = {
            "name": f"{parent}/tasks/{task_name(payload)}",
            "http_request": {
                "http_method": "POST",
                "url": f"{s.worker_url}/tasks/{payload.kind}",
                "headers": {"Content-Type": "application/json"},
                "body": payload.model_dump_json().encode(),
                "oidc_token": {"service_account_email": s.tasks_sa, "audience": s.worker_url},
            },
            "dispatch_deadline": duration_pb2.Duration(seconds=DISPATCH_DEADLINE_S),
        }
        if delay_s > 0:
            ts = timestamp_pb2.Timestamp()
            ts.FromDatetime(datetime.now(UTC) + timedelta(seconds=delay_s))
            task["schedule_time"] = ts
        try:
            client.create_task(request={"parent": parent, "task": task})
        except AlreadyExists:
            logs.emit(
                "task_deduplicated",
                session_id=payload.sid,
                step=payload.kind,
                request_id=payload.request_id,
            )


Dispatcher = Callable[[TaskPayload, int], int]  # (payload, retry_count) -> HTTP status


class InMemoryQueue:
    """Combined/local/test queue: calls the handler wrapper directly, no HTTP. It emulates the
    Cloud Tasks queue (name dedup, one retry on 5xx), which is the queue's job, not the app's.

    `auto=True` (local dev) delivers each task on a background timer; otherwise tasks wait in
    `pending` until `drain()` (tests)."""

    def __init__(self, dispatcher: Dispatcher | None = None, auto: bool = False) -> None:
        self.dispatcher = dispatcher
        self.auto = auto
        self.pending: list[TaskPayload] = []
        self.seen: set[str] = set()
        self._lock = threading.Lock()

    def bind(self, dispatcher: Dispatcher) -> None:
        self.dispatcher = dispatcher

    def enqueue(self, payload: TaskPayload, delay_s: float = 0.0) -> None:
        name = task_name(payload)
        with self._lock:
            if name in self.seen:
                return
            self.seen.add(name)
            if not self.auto:
                self.pending.append(payload)
                return
        timer = threading.Timer(delay_s, self.deliver, args=(payload,))
        timer.daemon = True
        timer.start()

    def deliver(self, payload: TaskPayload) -> int:
        if self.dispatcher is None:
            raise RuntimeError("no dispatcher bound")
        retry = 0
        while True:
            status = self.dispatcher(payload, retry)
            if 200 <= status < 300 or retry + 1 >= MAX_ATTEMPTS:
                return status
            retry += 1

    def drain(self, limit: int = 100) -> None:
        """Deliver pending tasks (including ones they enqueue) in order; delays are ignored."""
        for _ in range(limit):
            with self._lock:
                if not self.pending:
                    return
                payload = self.pending.pop(0)
            self.deliver(payload)
        raise RuntimeError("drain limit reached")


def build_queue(settings: Settings) -> TaskQueue | None:
    if settings.service_mode == "combined":
        return InMemoryQueue(auto=settings.env == "local")
    if settings.tasks_queue:
        return CloudTasksQueue(settings)
    return None
