"""Run engine: start a run and drive it to a terminal state (R8, D9, D13, D15).

Flow: ``start_run`` (sync, needs a running loop) selects items, writes run.json
(state ``running``), takes the run lock and schedules one ``asyncio.Task``:

1. Preflight: dataset ready (``<data_dir>/download.json`` status, only when the
   metadata says ``data_required``), contracts load, the adapter builds every request,
   each gets ``request_id=<run_id>:<item_id>`` when the adapter gave none, and each
   validates. Any failure ends the run ``failed`` with zero POSTs.
2. Canary: the first item alone. Run-level fatal canary outcomes end the run ``failed``
   with no fan-out: ``network`` (connection refused...), an ``invalid_response``
   (schema mismatch), HTTP 401/403 (auth). Any other
   canary failure (timeout, rate limit, 5xx, request_id mismatch) is an ordinary item
   failure: it is stored and the run continues. The canary's item file is always written.
3. The rest under ``asyncio.Semaphore(concurrency)``; each completion writes its item
   file, updates in-memory counters and calls ``on_progress``.
4. End: totals recomputed from item files, state and ``finished_at`` stored, lock
   released, then ``on_finish(run_id)`` (sync or async; errors are logged, never raised).

Terminal states: ``finished`` (may include failed items), ``aborted`` (``abort()``:
dispatch stops, in-flight items finish), ``failed`` (run-level error, recorded in
run.json as ``error {kind, message, code?}``), ``aborted_cost`` (optional ``max_cost_usd``
cap reached: spent this invocation = sum of ``run_info.cost_usd`` >= cap; dispatch stops,
in-flight items finish). With a cap set, a response lacking ``cost_usd`` fails closed:
dispatch stops, in-flight items finish, run ends ``failed`` with error kind ``cost_missing``.
No cap = no cost handling at all. ``resume`` (below) re-sends failed/missing items and takes
its own cap. ``_RunDriver._stop_reason`` and ``_after_result`` are the extension points.

``probe`` (bottom) is the zero-spend reachability/version check; ``estimate`` lives in
``estimate.py``.

Nothing here logs or stores request/response text beyond the item files themselves.
"""

from __future__ import annotations

import asyncio
import hashlib
import inspect
import json
import logging
import os
import shutil
import subprocess
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

from iaudit_eval import contracts, download, paths, store
from iaudit_eval.client import AuditClient, Outcome
from iaudit_eval.datasets import Dataset, load
from iaudit_eval.datasets.base import DatasetError
from iaudit_eval.log import log_event
from iaudit_eval.selection import select

DEFAULT_CONCURRENCY = 4
KEEP_CAP: Any = object()  # resume(max_cost_usd=KEEP_CAP): keep the stored cap; None clears it
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


class ResumeError(Exception):
    """The run cannot be resumed (unknown state, dataset changed or still missing)."""


class FingerprintChanged(Exception):
    """The first new response differs from the run fingerprint (models / prompt hashes)."""

    def __init__(self, message: str, changes: dict | None = None):
        super().__init__(message)
        self.changes = changes or {}


class SchemaVersionChanged(FingerprintChanged):
    """Backend schema_version differs from the run's; always refused, even with allow_mixed."""


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
        """Wait for the run; a refused resume raises ``FingerprintChanged`` here."""
        await asyncio.shield(self._task)
        if self._driver.refused is not None:
            raise self._driver.refused
        return self.state

    def abort(self) -> None:
        """Stop dispatching; in-flight items finish; the run ends ``aborted``."""
        self._driver.abort_event.set()

    def drain(self) -> None:
        """Stop dispatching; in-flight items finish; no terminal state is stored.

        The run stays ``running`` in run.json, so once the lock is released it reads as
        ``interrupted`` and is resumable (server shutdown). If every item was already
        processed the run still ends ``finished``.
        """
        self._driver.drain_event.set()


class _RunDriver:
    def __init__(self, *, run_id, dataset, items, runs_root, data_root, client, owns_client,
                 concurrency, on_progress, on_finish, lock, max_cost_usd=None,
                 datasets_root=None):  # fmt: skip
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
        self.datasets_root = datasets_root
        self.state = "running"
        self.abort_event = asyncio.Event()
        self.drain_event = asyncio.Event()
        self.processed: set[str] = set()
        self.requests: dict[str, dict] = {}
        self.done = 0
        self.failed = 0
        self._statuses: dict[str, str] = {}
        self.cost: float | None = None
        self.error: dict | None = None
        self._schema_set = False
        self._fingerprint_set = False
        self.refused: FingerprintChanged | None = None
        self.total = len(items)
        self.max_cost_usd = max_cost_usd
        self.spent = 0.0  # cost reported in this invocation only
        self.cost_missing = False

    # ----- extension points (cost cap, resume) -----

    def _stop_reason(self) -> str | None:
        """Non-None stops dispatch."""
        if self.cost_missing:
            return "cost_missing"
        if self.abort_event.is_set():
            return "aborted"
        if self.max_cost_usd is not None and self.spent >= self.max_cost_usd:
            return "aborted_cost"
        if self.drain_event.is_set():
            return "drained"
        return None

    def _after_result(self, item_record: dict) -> None:
        """Called after each stored item (cost accounting hooks in here)."""
        info = item_record.get("run_info") or {}
        cost = info.get("cost_usd")
        if isinstance(cost, int | float) and not isinstance(cost, bool):
            self.cost = (self.cost or 0.0) + cost
            self.spent += cost
        elif self.max_cost_usd is not None and item_record.get("response") is not None:
            self.cost_missing = True  # fail closed: a cap we cannot enforce

    # ----- driver -----

    async def run(self) -> None:
        try:
            try:
                await asyncio.to_thread(self._preflight)
                await self._dispatch()
            except _Preflight as e:
                self._fail(e.kind, e.message)
            except Exception as e:  # unexpected engine fault: run-level failure, no text
                log_event("engine_error", level=logging.ERROR, run_id=self.run_id,
                          exc_class=type(e).__name__)  # fmt: skip
                self._fail("engine_error", f"unexpected {type(e).__name__}")
            self._finish()
        finally:
            try:
                if self.owns_client:
                    await self.client.aclose()
            finally:
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
        if rec is None:  # refused by _accept
            return
        if _canary_fatal(out):
            self._fail("canary_failed", f"canary failed ({out.kind})",
                       code=out.error_code, http_status=out.http_status)  # fmt: skip
            return
        sem = asyncio.Semaphore(self.concurrency)

        stopped = False

        async def one(item):
            nonlocal stopped
            async with sem:
                if stopped or self._stop_reason():
                    return
                try:
                    await self._process(item)
                except BaseException:
                    stopped = True  # set before releasing the semaphore to queued workers
                    raise

        workers = [asyncio.create_task(one(item)) for item in rest]
        drained = asyncio.gather(*workers, return_exceptions=True)
        try:
            results = await asyncio.shield(drained)
        except asyncio.CancelledError:
            stopped = True
            for worker in workers:
                worker.cancel()
            # Cancellation can itself be repeated while a transport cleans up. Keep
            # owning the run until every child has stopped accessing its client/files.
            while not drained.done():
                try:
                    await asyncio.shield(drained)
                except asyncio.CancelledError:
                    continue
            raise
        for result in results:
            if isinstance(result, BaseException):
                raise result

    def _accept(self, out: Outcome) -> bool:
        """Hook: False discards the outcome before anything is written (resume guard)."""
        return True

    async def _process(self, item) -> tuple[dict | None, Outcome]:
        req = self.requests[item.id]
        started = _now()
        t0 = time.monotonic()
        out = await self.client.audit(req)
        latency_ms = int((time.monotonic() - t0) * 1000)
        if not self._accept(out):
            return None, out
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
        self.processed.add(item.id)
        previous = self._statuses.get(item.id)
        if previous == "failed":
            self.failed -= 1
        elif previous == "ok":
            self.done -= 1
        self._statuses[item.id] = out.status
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
        """Capture the first schema and, independently, the first available run_info."""
        fields: dict[str, Any] = {}
        if not self._schema_set:
            fields["schema_version"] = resp.get("schema_version")
            self._schema_set = True
        info = resp.get("run_info")
        if not self._fingerprint_set and info:
            fields["fingerprint"] = {
                "models": info.get("models"), "prompt_hashes": info.get("prompt_hashes"),
            }  # fmt: skip
            self._fingerprint_set = True
        if fields:
            store.update_run(self.runs_root, self.run_id, **fields)

    def _snapshot(self) -> RunProgress:
        return RunProgress(self.run_id, self.state, self.done, self.failed,
                           self.total, self.cost)  # fmt: skip

    def _progress(self) -> None:
        if self.on_progress is None:
            return
        try:
            self.on_progress(self._snapshot())
        except Exception as e:
            log_event("progress_callback_error", level=logging.WARNING, run_id=self.run_id,
                      exc_class=type(e).__name__)  # fmt: skip

    def _finish(self) -> None:
        if self.state == "running" and self.cost_missing:
            self._fail("cost_missing", "a cost cap is set but the backend response "
                       "reports no cost_usd; the cap cannot be enforced")  # fmt: skip
        elif self.state == "running":
            reason = self._stop_reason()
            if len(self.processed) >= len(self.items):
                self.state = "finished"  # a stop fired after the last dispatch: nothing left
            elif reason == "drained":
                # Leave run.json "running": interrupted once the lock is released.
                log_event("run_drained", run_id=self.run_id, items_done=self.done,
                          items_failed=self.failed)  # fmt: skip
                self._progress()
                return
            else:
                self.state = reason if reason in ("aborted", "aborted_cost") else "finished"
        fields: dict[str, Any] = {"state": self.state, "finished_at": _now()}
        if self.error:
            fields["error"] = self.error
        store.update_run(self.runs_root, self.run_id, **fields)
        store.refresh_totals(self.runs_root, self.run_id)
        log_event("run_finished", run_id=self.run_id, state=self.state,
                  items_done=self.done, items_failed=self.failed)  # fmt: skip
        self._progress()

    def _auto_score(self, run_id: str) -> None:
        from . import scoring  # lazy: scoring imports capture_git from this module

        scoring.score(run_id, runs_root=self.runs_root, data_root=self.data_root,
                      datasets_root=self.datasets_root, dataset=self.dataset)

    async def _call_finish(self) -> None:
        if self.on_finish is None:
            return
        try:
            if self.on_finish is AUTO_SCORE:
                await asyncio.to_thread(self._auto_score, self.run_id)
                return
            res = self.on_finish(self.run_id)
            if inspect.isawaitable(res):
                await res
        except Exception as e:
            log_event("finish_hook_error", level=logging.WARNING, run_id=self.run_id,
                      exc_class=type(e).__name__)  # fmt: skip


# Default ``on_finish``: score the run (metrics.json). Pass ``None`` to disable, or a
# callable to replace it. Scoring errors are logged only and never change run state.
AUTO_SCORE: Any = object()


async def _prepare_in_thread(prepare, *args, **kwargs) -> dict:
    task = asyncio.create_task(asyncio.to_thread(prepare, *args, **kwargs))
    try:
        return await asyncio.shield(task)
    except asyncio.CancelledError:
        # A thread cannot be cancelled. Reap its result before releasing a lock it
        # may already own; a created run then remains safely resumable/interrupted.
        while not task.done():
            try:
                await asyncio.shield(task)
            except asyncio.CancelledError:
                continue
            except Exception:
                break
        if not task.cancelled() and task.exception() is None:
            task.result()["lock"].release()
        raise


def _spawn_prepared(
    prepared, *, client, transport, on_progress, on_finish, resume_run,
) -> RunHandle:
    values = dict(prepared)
    base_url = values.pop("base_url")
    totals = values.pop("totals", None)
    total = values.pop("total", None)
    statuses = values.pop("statuses", {})
    try:
        audit_client = client or AuditClient(base_url, transport=transport)
        driver_type = _ResumeDriver if resume_run else _RunDriver
        driver = driver_type(
            **values, client=audit_client, owns_client=client is None,
            on_progress=on_progress, on_finish=on_finish,
        )
        if totals is not None:
            driver._statuses = statuses
            driver.done = totals["ok"] + totals["partial"]
            driver.failed = totals["failed"]
            driver.cost = totals["cost_usd"]
            driver.total = total
        task = asyncio.get_running_loop().create_task(driver.run())
        return RunHandle(values["run_id"], driver, task)
    except BaseException:
        values["lock"].release()
        raise


def _prepare_start(
    dataset, selection, *, base_url, max_cost_usd, tags, concurrency, runs_root, data_root,
    datasets_root=None,
) -> dict:
    if concurrency < 1:
        raise ValueError("concurrency must be >= 1")
    selection = selection or Selection()
    if isinstance(dataset, str):
        dataset = load(dataset, root=datasets_root, data_root=data_root)
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
        "warnings": list(dict.fromkeys(download.hash_warnings(dataset, data_root=data_root))),
        **capture_git(),
    }
    run_id = store.create_run(runs_root, run_meta)
    try:
        lock = store.RunLock(runs_root, run_id).acquire()
    except BaseException:
        shutil.rmtree(store.run_dir(runs_root, run_id), ignore_errors=True)  # no orphan "running"
        raise
    return {
        "run_id": run_id, "dataset": dataset, "items": items, "runs_root": runs_root,
        "data_root": data_root, "concurrency": concurrency, "lock": lock,
        "max_cost_usd": max_cost_usd, "base_url": base_url, "datasets_root": datasets_root,
    }


def start_run(
    dataset: Dataset | str,
    selection: Selection | None = None,
    *,
    base_url: str,
    max_cost_usd: float | None = None,
    tags: dict | None = None,
    concurrency: int = DEFAULT_CONCURRENCY,
    on_progress: Callable[[RunProgress], None] | None = None,
    on_finish: Callable[[str], Awaitable[None] | None] | None = AUTO_SCORE,
    client: AuditClient | None = None,
    transport=None,
    runs_root: Path | None = None,
    data_root: Path | None = None,
    datasets_root: Path | None = None,
) -> RunHandle:
    """Create and schedule a run; synchronous preparation needs a running loop."""
    asyncio.get_running_loop()
    prepared = _prepare_start(
        dataset, selection, base_url=base_url, max_cost_usd=max_cost_usd, tags=tags,
        concurrency=concurrency, runs_root=runs_root, data_root=data_root,
        datasets_root=datasets_root,
    )
    return _spawn_prepared(
        prepared, client=client, transport=transport, on_progress=on_progress,
        on_finish=on_finish, resume_run=False,
    )


async def start_run_async(
    dataset: Dataset | str,
    selection: Selection | None = None,
    *,
    base_url: str,
    max_cost_usd: float | None = None,
    tags: dict | None = None,
    concurrency: int = DEFAULT_CONCURRENCY,
    on_progress: Callable[[RunProgress], None] | None = None,
    on_finish: Callable[[str], Awaitable[None] | None] | None = AUTO_SCORE,
    client: AuditClient | None = None,
    transport=None,
    runs_root: Path | None = None,
    data_root: Path | None = None,
    datasets_root: Path | None = None,
) -> RunHandle:
    """Prepare filesystem/adapter/git work in a thread, then spawn on the caller loop."""
    prepared = await _prepare_in_thread(
        _prepare_start, dataset, selection, base_url=base_url,
        max_cost_usd=max_cost_usd, tags=tags, concurrency=concurrency,
        runs_root=runs_root, data_root=data_root, datasets_root=datasets_root,
    )
    return _spawn_prepared(
        prepared, client=client, transport=transport, on_progress=on_progress,
        on_finish=on_finish, resume_run=False,
    )


# ---------- resume (R8, D7, D8) ----------

class _ResumeDriver(_RunDriver):
    """Re-sends failed/missing items; guards the first new response against the fingerprint.

    On ``FingerprintChanged`` nothing from the refused response is written, dispatch
    stops and run.json is restored to its pre-resume content (so the run stays in its
    earlier state, ``interrupted`` if it was running, and is resumable again). Failed
    items re-sent before the first valid response may have been rewritten (still failed).
    """

    def __init__(self, *, snapshot: dict, allow_mixed: bool, prior_state: str,
                 snapshot_mtime_ns: int | None = None, **kw):
        super().__init__(**kw)
        self.snapshot = snapshot
        self.snapshot_mtime_ns = snapshot_mtime_ns
        self.allow_mixed = allow_mixed
        self.prior_state = prior_state
        self.stored_fp = snapshot.get("fingerprint")
        self.stored_schema = snapshot.get("schema_version")
        self._verified = self.stored_fp is None and self.stored_schema is None
        self._schema_set = self.stored_schema is not None
        self._fingerprint_set = self.stored_fp is not None

    def _stop_reason(self) -> str | None:
        return "refused" if self.refused is not None else super()._stop_reason()

    def _accept(self, out: Outcome) -> bool:
        if self.refused is not None:
            return False
        if not out.ok or self._verified:
            return True
        try:
            self._check(out.response)
        except FingerprintChanged as e:
            self.refused = e
            return False
        return True

    def _check(self, resp: dict) -> None:
        sv = resp.get("schema_version")
        if self.stored_schema and sv != self.stored_schema:
            raise SchemaVersionChanged(
                "backend schema_version changed since the run started",
                {"schema_version": {"was": self.stored_schema, "now": sv}},
            )
        if self.stored_fp is None:
            self._verified = True
            return
        info = resp.get("run_info")
        if not info:
            return  # nothing to compare; keep guarding
        self._verified = True
        new = {"models": info.get("models"), "prompt_hashes": info.get("prompt_hashes")}
        changes = {
            k: {"was": self.stored_fp.get(k), "now": new[k]}
            for k in new
            if new[k] != self.stored_fp.get(k)
        }
        if not changes:
            return
        if not self.allow_mixed:
            raise FingerprintChanged("models or prompts changed since the run started", changes)
        run = store.load_run(self.runs_root, self.run_id)
        run["resumes"][-1]["fingerprint"] = new
        run["mixed"] = True
        run["warnings"] = [*run.get("warnings", []), "resume mixed fingerprints (allow_mixed)"]
        store.atomic_write_json(store.run_dir(self.runs_root, self.run_id) / "run.json", run)

    def _finish(self) -> None:
        if self.refused is None:
            super()._finish()
            return
        self.state = self.prior_state
        path = store.run_dir(self.runs_root, self.run_id) / "run.json"
        store.atomic_write_json(path, self.snapshot)
        if self.snapshot_mtime_ns is not None:
            # Same content as before the resume: keep its mtime so metrics stay current.
            os.utime(path, ns=(self.snapshot_mtime_ns, self.snapshot_mtime_ns))
        log_event("resume_refused", level=logging.WARNING, run_id=self.run_id,
                  reason=type(self.refused).__name__)  # fmt: skip
        self._progress()


def _prepare_resume(
    run_id, *, max_cost_usd, allow_mixed, base_url, concurrency, runs_root, data_root, dataset,
    datasets_root=None,
) -> dict:
    lock = store.RunLock(runs_root, run_id).acquire()  # RunLockedError if concurrent
    try:
        run = store.load_run(runs_root, run_id)
        snapshot = json.loads(json.dumps(run))
        snapshot_mtime_ns = (store.run_dir(runs_root, run_id) / "run.json").stat().st_mtime_ns
        state = run["state"]
        if state not in store.STORED_STATES:
            raise ResumeError(f"cannot resume a run in state {state!r}")
        # We hold the lock, so a stored "running" means interrupted.
        prior_state = state
        if dataset is None:
            dataset = load(run["dataset"], root=datasets_root, data_root=data_root)
        meta = dataset.meta
        if meta.dataset_version != run.get("dataset_version"):
            raise ResumeError("dataset version changed since the run started")
        if state == "failed" and (run.get("error") or {}).get("kind") == "dataset_not_ready":
            try:
                _dataset_ready(meta, data_root)
            except _Preflight as e:
                raise ResumeError(e.message) from e
        have = {it["item_id"]: it for it in store.iter_items(runs_root, run_id)}
        by_id = {i.id: i for i in dataset.items(run["split"])}
        try:
            todo = [
                by_id[iid] for iid in run["item_ids"]
                if iid not in have or have[iid].get("status") == "failed"
            ]  # fmt: skip
        except KeyError as e:
            raise ResumeError("dataset no longer contains a run item") from e

        store.clean_stale_tmp(runs_root, run_id)
        git = capture_git()
        last = (run.get("resumes") or [None])[-1] or run
        warnings = [*run.get("warnings", []),
                    *download.hash_warnings(dataset, data_root=data_root)]
        if (git["git_commit"], git["git_dirty"]) != (last.get("git_commit"), last.get("git_dirty")):
            warnings.append("git commit or dirty state changed since the previous run/resume")
        entry = {
            "at": _now(), "git_commit": git["git_commit"], "git_dirty": git["git_dirty"],
            "fingerprint": run.get("fingerprint"), "allow_mixed": allow_mixed,
        }  # fmt: skip
        new = {k: v for k, v in run.items() if k != "error"}
        new.update(state="running", finished_at=None, warnings=list(dict.fromkeys(warnings)),
                   resumes=[*run.get("resumes", []), entry])  # fmt: skip
        if max_cost_usd is not KEEP_CAP:
            new["max_cost_usd"] = max_cost_usd  # None clears the stored cap
        store.atomic_write_json(store.run_dir(runs_root, run_id) / "run.json", new)

        totals = store.compute_totals(runs_root, run_id)
        return {
            "snapshot": snapshot, "snapshot_mtime_ns": snapshot_mtime_ns,
            "allow_mixed": allow_mixed, "prior_state": prior_state,
            "run_id": run_id, "dataset": dataset, "items": todo, "runs_root": runs_root,
            "data_root": data_root, "lock": lock, "max_cost_usd": new.get("max_cost_usd"),
            "datasets_root": datasets_root,
            "concurrency": concurrency or run.get("concurrency") or DEFAULT_CONCURRENCY,
            "base_url": base_url or run["backend_url"], "totals": totals,
            "total": len(run["item_ids"]),
            "statuses": {iid: record["status"] for iid, record in have.items()},
        }
    except BaseException:
        lock.release()
        raise


def resume(
    run_id: str,
    *,
    max_cost_usd: float | None = KEEP_CAP,
    allow_mixed: bool = False,
    base_url: str | None = None,
    concurrency: int | None = None,
    on_progress: Callable[[RunProgress], None] | None = None,
    on_finish: Callable[[str], Awaitable[None] | None] | None = AUTO_SCORE,
    client: AuditClient | None = None,
    transport=None,
    runs_root: Path | None = None,
    data_root: Path | None = None,
    dataset: Dataset | None = None,
    datasets_root: Path | None = None,
) -> RunHandle:
    """Resume failed/missing items with synchronous preparation on the caller loop."""
    asyncio.get_running_loop()
    prepared = _prepare_resume(
        run_id, max_cost_usd=max_cost_usd, allow_mixed=allow_mixed,
        base_url=base_url, concurrency=concurrency, runs_root=runs_root,
        data_root=data_root, dataset=dataset, datasets_root=datasets_root,
    )
    return _spawn_prepared(
        prepared, client=client, transport=transport, on_progress=on_progress,
        on_finish=on_finish, resume_run=True,
    )


async def resume_async(
    run_id: str,
    *,
    max_cost_usd: float | None = KEEP_CAP,
    allow_mixed: bool = False,
    base_url: str | None = None,
    concurrency: int | None = None,
    on_progress: Callable[[RunProgress], None] | None = None,
    on_finish: Callable[[str], Awaitable[None] | None] | None = AUTO_SCORE,
    client: AuditClient | None = None,
    transport=None,
    runs_root: Path | None = None,
    data_root: Path | None = None,
    dataset: Dataset | None = None,
    datasets_root: Path | None = None,
) -> RunHandle:
    """Prepare a resume in a worker thread, then spawn on the caller loop."""
    prepared = await _prepare_in_thread(
        _prepare_resume, run_id, max_cost_usd=max_cost_usd, allow_mixed=allow_mixed,
        base_url=base_url, concurrency=concurrency, runs_root=runs_root,
        data_root=data_root, dataset=dataset, datasets_root=datasets_root,
    )
    return _spawn_prepared(
        prepared, client=client, transport=transport, on_progress=on_progress,
        on_finish=on_finish, resume_run=True,
    )


# ---------- probe (D9) ----------

@dataclass(frozen=True)
class ProbeResult:
    reachable: bool
    backend_schema_version: str | None
    accepts_version: bool


async def probe(
    base_url: str, *, transport=None, timeout_s: float = 10
) -> ProbeResult:
    """Zero-spend reachability and version check.

    ``GET /healthz`` then one ``POST /v1/audit`` whose body is only
    ``{"schema_version": <loaded>}``. The deliberately incomplete body is rejected
    by ordinary request validation without audit work. A 2xx or 4xx answer with the
    current schema version counts as accepted; 5xx or an unreadable answer
    is reachable but not a version verdict (``accepts_version`` False). A failed GET or
    POST means ``reachable`` False. Lives here (not in client.py) because it composes
    the client with the loaded contract version for the engine's callers.
    """
    client = AuditClient(base_url, timeout_s=timeout_s, transport=transport)
    try:
        if not await client.healthz():
            return ProbeResult(False, None, False)
        try:
            async with asyncio.timeout(timeout_s):
                resp = await client._http.post(
                    "/v1/audit", json={"schema_version": contracts.schema_version()}
                )
        except (httpx.HTTPError, TimeoutError):
            return ProbeResult(False, None, False)
    finally:
        await client.aclose()
    try:
        body = resp.json()
    except ValueError:
        body = None
    version = body.get("schema_version") if isinstance(body, dict) else None
    version = version if isinstance(version, str) else None
    status = resp.status_code
    valid_body = (
        not contracts.validate_response(body) if 200 <= status < 300
        else not contracts.validate_error(body) and body["status"] == status
    )
    accepts = version == contracts.schema_version() and 200 <= status < 500 and valid_body
    return ProbeResult(True, version, accepts)
