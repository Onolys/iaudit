"""Run engine: start a run and drive it to a terminal state (R8, D9, D13, D15).

Flow: ``start_run`` (sync, needs a running loop) selects items, writes run.json
(state ``running``), takes the run lock and schedules one ``asyncio.Task``:

1. Preflight: dataset ready (``<data_dir>/download.json`` status, only when the
   metadata says ``data_required``), contracts load, the adapter builds every request,
   each gets ``request_id=<run_id>:<item_id>`` when the adapter gave none, and each
   validates. Any failure ends the run ``failed`` with zero POSTs.
2. Canary: the first item alone. Run-level fatal canary outcomes end the run ``failed``
   with no fan-out: ``network`` (connection refused...), an ``unsupported_version``
   error, an ``invalid_response`` (schema mismatch), HTTP 401/403 (auth). Any other
   canary failure (timeout, rate limit, 5xx, request_id mismatch) is an ordinary item
   failure: it is stored and the run continues. The canary's item file is always written.
3. The rest under ``asyncio.Semaphore(concurrency)``; each completion writes its item
   file, updates in-memory counters and calls ``on_progress``.
4. End: totals recomputed from item files, state and ``finished_at`` stored, lock
   released, then ``on_finish(run_id)`` (sync or async; errors are logged, never raised).

Terminal states: ``finished`` (may include failed items), ``aborted`` (``abort()``:
dispatch stops, in-flight items finish), ``failed`` (run-level error, recorded in
run.json as ``error {kind, message, code?}``). ``aborted_cost`` and resume belong to
later tasks; ``_RunDriver._stop_reason`` and ``_after_result`` are the extension points.

Nothing here logs or stores request/response text beyond the item files themselves.
"""

from __future__ import annotations

import asyncio
import hashlib
import inspect
import json
import logging
import subprocess
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from iaudit_eval import contracts, paths, store
from iaudit_eval.client import AuditClient, Outcome
from iaudit_eval.datasets import Dataset, load
from iaudit_eval.datasets.base import DatasetError
from iaudit_eval.log import log_event
from iaudit_eval.selection import select

DEFAULT_CONCURRENCY = 4
_FATAL_HTTP = frozenset({401, 403})


@dataclass(frozen=True)
class Selection:
    split: str | None = None  # None = dataset default_split
    n: int | None = None  # None = all items of the split
    seed: int = 0


@dataclass(frozen=True)
class RunProgress:
    run_id: str
    state: str
    done: int
    failed: int
    total: int
    cost_usd: float | None


class _Preflight(Exception):
    def __init__(self, kind: str, message: str):
        super().__init__(message)
        self.kind = kind
        self.message = message


def _now() -> str:
    return datetime.now(UTC).isoformat()


# ---------- git capture ----------

def _git(*args: str) -> bytes | None:
    try:
        r = subprocess.run(
            ["git", *args], cwd=paths.repo_root(), capture_output=True, timeout=30, check=False
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return r.stdout if r.returncode == 0 else None


def capture_git() -> dict[str, Any]:
    """Commit, dirty flag and sha256 of ``git diff HEAD``; all None without git."""
    head = _git("rev-parse", "HEAD")
    status = _git("status", "--porcelain")
    diff = _git("diff", "HEAD")
    return {
        "git_commit": head.decode().strip() if head else None,
        "git_dirty": bool(status.strip()) if status is not None else None,
        "git_diff_sha256": hashlib.sha256(diff).hexdigest() if diff is not None else None,
    }


# ---------- helpers ----------

def _dataset_ready(meta, data_root: Path | None) -> None:
    if not meta.data_required:
        return
    root = Path(data_root) if data_root is not None else paths.data_dir()
    try:
        status = json.loads((root / meta.name / "download.json").read_text("utf-8")).get("status")
    except (OSError, ValueError, AttributeError):
        status = None
    if status != "ready":
        raise _Preflight("dataset_not_ready", f"dataset data is not ready (status: {status})")


def _issue_dicts(issues) -> list[dict]:
    return [{"path": i.path, "message": i.message} for i in issues]


def _failure(out: Outcome) -> dict:
    f: dict[str, Any] = {"kind": out.kind, "issues": _issue_dicts(out.issues)}
    if out.http_status is not None:
        f["http_status"] = out.http_status
    if out.error_code is not None:
        f["error_code"] = out.error_code
    if out.error_message is not None:
        f["message"] = out.error_message
    return f


def _canary_fatal(out: Outcome) -> bool:
    if out.ok:
        return False
    return (
        out.kind in ("network", "invalid_response")
        or out.error_code == "unsupported_version"
        or out.http_status in _FATAL_HTTP
    )


class RunHandle:
    """Handle on a running engine task."""

    def __init__(self, run_id: str, driver: _RunDriver, task: asyncio.Task):
        self.run_id = run_id
        self._driver = driver
        self._task = task

    @property
    def state(self) -> str:
        return self._driver.state

    async def wait(self) -> str:
        await asyncio.shield(self._task)
        return self.state

    def abort(self) -> None:
        """Stop dispatching; in-flight items finish; the run ends ``aborted``."""
        self._driver.abort_event.set()


class _RunDriver:
    def __init__(self, *, run_id, dataset, items, runs_root, data_root, client, owns_client,
                 concurrency, on_progress, on_finish, lock):  # fmt: skip
        self.run_id = run_id
        self.dataset = dataset
        self.items = items
        self.runs_root = runs_root
        self.data_root = data_root
        self.client = client
        self.owns_client = owns_client
        self.concurrency = concurrency
        self.on_progress = on_progress
        self.on_finish = on_finish
        self.lock = lock
        self.state = "running"
        self.abort_event = asyncio.Event()
        self.requests: dict[str, dict] = {}
        self.done = 0
        self.failed = 0
        self.cost: float | None = None
        self.error: dict | None = None
        self._identity_set = False

    # ----- extension points for cost cap / resume (later tasks) -----

    def _stop_reason(self) -> str | None:
        """Non-None stops dispatch. Only abort for now."""
        return "aborted" if self.abort_event.is_set() else None

    def _after_result(self, item_record: dict) -> None:
        """Called after each stored item (cost accounting hooks in here)."""
        info = item_record.get("run_info") or {}
        cost = info.get("cost_usd")
        if isinstance(cost, int | float) and not isinstance(cost, bool):
            self.cost = (self.cost or 0.0) + cost

    # ----- driver -----

    async def run(self) -> None:
        try:
            try:
                self._preflight()
                await self._dispatch()
            except _Preflight as e:
                self._fail(e.kind, e.message)
            except Exception as e:  # unexpected engine fault: run-level failure, no text
                log_event("engine_error", level=logging.ERROR, run_id=self.run_id,
                          exc_class=type(e).__name__)  # fmt: skip
                self._fail("engine_error", f"unexpected {type(e).__name__}")
            self._finish()
        finally:
            if self.owns_client:
                await self.client.aclose()
            self.lock.release()
        await self._call_finish()

    def _fail(self, kind: str, message: str, **extra: Any) -> None:
        self.state = "failed"
        self.error = {"kind": kind, "message": message, **extra}

    def _preflight(self) -> None:
        try:
            contracts.schema_version()
        except Exception as e:
            raise _Preflight("contracts", f"contracts failed to load ({type(e).__name__})") from e
        _dataset_ready(self.dataset.meta, self.data_root)
        for item in self.items:
            try:
                req = dict(self.dataset.adapter.to_request(item))
            except Exception as e:
                raise _Preflight(
                    "preflight", f"adapter could not build request for {item.id} "
                    f"({type(e).__name__})",
                ) from e  # fmt: skip
            if not req.get("request_id"):
                req["request_id"] = f"{self.run_id}:{item.id}"
            issues = contracts.validate_request(req)
            if issues:
                raise _Preflight(
                    "preflight", f"request for {item.id} fails the contract: "
                    + "; ".join(str(i) for i in issues[:5]),
                )  # fmt: skip
            self.requests[item.id] = req

    async def _dispatch(self) -> None:
        if not self.items:
            return
        first, rest = self.items[0], self.items[1:]
        if self._stop_reason():
            return
        rec, out = await self._process(first)
        if _canary_fatal(out):
            self._fail("canary_failed", f"canary failed ({out.kind})",
                       code=out.error_code, http_status=out.http_status)  # fmt: skip
            return
        sem = asyncio.Semaphore(self.concurrency)

        async def one(item):
            async with sem:
                if self._stop_reason():
                    return
                await self._process(item)

        await asyncio.gather(*(one(i) for i in rest))

    async def _process(self, item) -> tuple[dict, Outcome]:
        req = self.requests[item.id]
        started = _now()
        t0 = time.monotonic()
        out = await self.client.audit(req)
        latency_ms = int((time.monotonic() - t0) * 1000)
        resp = out.response if out.ok else None
        rec: dict[str, Any] = {
            "item_id": item.id,
            "doc_id": item.doc_id,
            "status": out.status,
            "attempts": out.attempts,
            "started_at": started,
            "finished_at": _now(),
            "latency_ms": latency_ms,
            "request": req,
            "response": resp,
            "response_status": resp.get("status") if resp else None,
            "run_info": resp.get("run_info") if resp else None,
            "failure": None if out.ok else _failure(out),
        }
        store.write_item(self.runs_root, self.run_id, rec)
        if out.ok:
            self.done += 1
            self._set_identity(resp)
        else:
            self.failed += 1
        self._after_result(rec)
        log_event("item_done", run_id=self.run_id, item_id=item.id, status=out.status,
                  kind=out.kind or "", duration_ms=latency_ms)  # fmt: skip
        self._progress()
        return rec, out

    def _set_identity(self, resp: dict) -> None:
        """schema_version and fingerprint from the first valid response."""
        if self._identity_set:
            return
        self._identity_set = True
        fields: dict[str, Any] = {"schema_version": resp.get("schema_version")}
        info = resp.get("run_info")
        if info:
            fields["fingerprint"] = {
                "models": info.get("models"), "prompt_hashes": info.get("prompt_hashes"),
            }  # fmt: skip
        store.update_run(self.runs_root, self.run_id, **fields)

    def _snapshot(self) -> RunProgress:
        return RunProgress(self.run_id, self.state, self.done, self.failed,
                           len(self.items), self.cost)  # fmt: skip

    def _progress(self) -> None:
        if self.on_progress is None:
            return
        try:
            self.on_progress(self._snapshot())
        except Exception as e:
            log_event("progress_callback_error", level=logging.WARNING, run_id=self.run_id,
                      exc_class=type(e).__name__)  # fmt: skip

    def _finish(self) -> None:
        if self.state == "running":
            self.state = "aborted" if self.abort_event.is_set() else "finished"
        fields: dict[str, Any] = {"state": self.state, "finished_at": _now()}
        if self.error:
            fields["error"] = self.error
        store.update_run(self.runs_root, self.run_id, **fields)
        store.refresh_totals(self.runs_root, self.run_id)
        log_event("run_finished", run_id=self.run_id, state=self.state,
                  items_done=self.done, items_failed=self.failed)  # fmt: skip
        self._progress()

    async def _call_finish(self) -> None:
        if self.on_finish is None:
            return
        try:
            res = self.on_finish(self.run_id)
            if inspect.isawaitable(res):
                await res
        except Exception as e:
            log_event("finish_hook_error", level=logging.WARNING, run_id=self.run_id,
                      exc_class=type(e).__name__)  # fmt: skip


def start_run(
    dataset: Dataset | str,
    selection: Selection | None = None,
    *,
    base_url: str,
    max_cost_usd: float | None = None,
    tags: dict | None = None,
    concurrency: int = DEFAULT_CONCURRENCY,
    on_progress: Callable[[RunProgress], None] | None = None,
    on_finish: Callable[[str], Awaitable[None] | None] | None = None,
    client: AuditClient | None = None,
    transport=None,
    runs_root: Path | None = None,
    data_root: Path | None = None,
) -> RunHandle:
    """Create a run and drive it in a background task of the running event loop.

    ``client``/``transport``/``runs_root``/``data_root`` are injection points for tests
    and the UI server. Raises ``DatasetError`` for an unknown split (nothing is created).
    """
    if concurrency < 1:
        raise ValueError("concurrency must be >= 1")
    loop = asyncio.get_running_loop()
    selection = selection or Selection()
    if isinstance(dataset, str):
        dataset = load(dataset, data_root=data_root)
    meta = dataset.meta
    split = selection.split or meta.default_split
    if not split:
        raise DatasetError("no split given and the dataset declares no default_split")
    items = select(dataset.items(split), selection.n, selection.seed)

    mapping_version = getattr(dataset.adapter, "mapping_version", None)
    run_meta: dict[str, Any] = {
        "dataset": meta.name,
        "dataset_version": meta.dataset_version,
        "split": split,
        "n_requested": selection.n,
        "seed": selection.seed,
        "item_ids": [i.id for i in items],
        "concurrency": concurrency,
        "max_cost_usd": max_cost_usd,
        "tags": dict(tags or {}),
        "mapping_version": mapping_version() if callable(mapping_version) else None,
        "backend_url": base_url,
        **capture_git(),
    }
    run_id = store.create_run(runs_root, run_meta)
    lock = store.RunLock(runs_root, run_id).acquire()
    owns = client is None
    audit_client = client or AuditClient(base_url, transport=transport)
    driver = _RunDriver(
        run_id=run_id, dataset=dataset, items=items, runs_root=runs_root, data_root=data_root,
        client=audit_client, owns_client=owns, concurrency=concurrency,
        on_progress=on_progress, on_finish=on_finish, lock=lock,
    )  # fmt: skip
    task = loop.create_task(driver.run())
    return RunHandle(run_id, driver, task)
