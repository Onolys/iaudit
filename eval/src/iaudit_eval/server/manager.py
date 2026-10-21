"""Server-owned background work and dataset access with explicitly configured roots."""

from __future__ import annotations

import asyncio
from dataclasses import asdict
from pathlib import Path

import httpx

from iaudit_eval import contracts, download, engine, scoring, store
from iaudit_eval import estimate as estimates
from iaudit_eval.datasets import Dataset, load
from iaudit_eval.datasets.base import DatasetError
from iaudit_eval.log import log_event
from iaudit_eval.server.guards import (
    ApiError,
    not_found,
    resolve_under,
    validate_dataset_id,
    validate_item_id,
    validate_run_id,
)


class _BorrowedTransport(httpx.AsyncBaseTransport):
    """Use an injected client's transport without letting a probe close its owner."""

    def __init__(self, transport):
        self.transport = transport

    async def handle_async_request(self, request):
        return await self.transport.handle_async_request(request)


class RunManager:
    """Own engine/download tasks and serialize mutations of each run's outputs."""

    def __init__(self, *, datasets_root: Path, data_root: Path, runs_root: Path):
        self.datasets_root = datasets_root
        self.data_root = data_root
        self.runs_root = runs_root
        self._datasets: dict[str, Dataset] = {}
        self._dataset_lock = asyncio.Lock()
        self._download_lock = asyncio.Lock()
        self.download_tasks: dict[str, asyncio.Task] = {}
        self._download_errors: dict[str, dict] = {}
        self._control_lock = asyncio.Lock()
        self._active_handle: engine.RunHandle | None = None
        self._active_task: asyncio.Task | None = None
        self._score_tasks: dict[str, asyncio.Task] = {}
        self.score_states: dict[str, str] = {}
        self.backend_schema_version: str | None = None
        self._closing = False
        self.backend_client = None
        self.backend_url = ""
        self._probe_transport = None

    def _load_dataset(self, name: str) -> Dataset:
        resolve_under(self.datasets_root, name)
        resolve_under(self.data_root, name)
        metadata = resolve_under(self.datasets_root, name, "metadata.json")
        resolve_under(self.datasets_root, name, "adapter.py")
        if not metadata.is_file():
            raise not_found("Dataset not found.")
        return load(name, root=self.datasets_root, data_root=self.data_root)

    async def get_dataset(self, name: str) -> Dataset:
        validate_dataset_id(name)
        async with self._dataset_lock:
            if name not in self._datasets:
                self._datasets[name] = await asyncio.to_thread(self._load_dataset, name)
            return self._datasets[name]

    def _dataset_names(self) -> list[str]:
        if not self.datasets_root.is_dir():
            return []
        names = []
        for path in sorted(self.datasets_root.iterdir()):
            try:
                validate_dataset_id(path.name)
                folder = resolve_under(self.datasets_root, path.name)
                resolve_under(self.datasets_root, path.name, "metadata.json")
                resolve_under(self.datasets_root, path.name, "adapter.py")
            except ApiError:
                continue
            if folder.is_dir() and (folder / "metadata.json").is_file():
                names.append(path.name)
        return names

    async def list_datasets(self) -> list[Dataset]:
        names = await asyncio.to_thread(self._dataset_names)
        return [await self.get_dataset(name) for name in names]

    async def dataset_sizes(self, dataset: Dataset) -> tuple[bool, dict[str, int | None]]:
        def read():
            present = True
            if dataset.meta.data_required:
                status = download.status(dataset, data_root=self.data_root)
                present = status["status"] == "ready" and all(
                    resolve_under(self.data_root, dataset.meta.name, file["filename"]).is_file()
                    for file in status.get("files", [])
                )
            if not present:
                return False, {name: None for name in dataset.meta.split_names()}
            return True, dataset.split_sizes()

        return await asyncio.to_thread(read)

    async def download_status(self, dataset: Dataset) -> dict:
        name = dataset.meta.name
        if name in self._download_errors:
            status = self._download_errors[name]
        else:
            task = self.download_tasks.get(name)
            if task is not None and not task.done():
                return {"status": "downloading", "files": []}
            status = await asyncio.to_thread(download.status, dataset, data_root=self.data_root)
        if status["status"] == "failed":
            # Persisted B2 diagnostics may include adapter/source content. Keep them
            # private and return a copy with a fixed public message, including restart.
            return {**status, "error": "Download failed."}
        return status

    async def start_download(self, dataset: Dataset) -> dict:
        name = dataset.meta.name
        async with self._download_lock:
            task = self.download_tasks.get(name)
            if task is None or task.done():
                self._download_errors.pop(name, None)
                self.download_tasks[name] = asyncio.create_task(self._download(dataset))
        return {"status": "downloading", "files": []}

    async def _download(self, dataset: Dataset) -> None:
        try:
            await asyncio.to_thread(download.download, dataset, data_root=self.data_root)
        except Exception as exc:
            # B2 records ordinary failures. Catch infrastructure errors outside its
            # write/try boundary without leaking exception text or losing the task.
            self._download_errors[dataset.meta.name] = {
                "status": "failed", "error": "Download failed.", "files": [],
            }
            log_event("download_task_failed", exc_class=type(exc).__name__)

    async def startup(self, backend_client, *, backend_url: str, injected: bool) -> None:
        self.backend_client = backend_client
        self.backend_url = backend_url
        if injected:
            transport = getattr(getattr(backend_client, "_http", None), "_transport", None)
            self._probe_transport = _BorrowedTransport(transport) if transport else None
        self._closing = False
        for run_id, state in self.score_states.items():
            if state == "running":
                self.score_states[run_id] = "pending"

    def _read_run(self, run_id: str) -> dict:
        validate_run_id(run_id)
        resolve_under(self.runs_root, run_id)
        path = resolve_under(self.runs_root, run_id, "run.json")
        if not path.is_file():
            raise not_found("Run not found.")
        resolve_under(self.runs_root, run_id, "run.lock")
        return store.load_run(self.runs_root, run_id)

    def _item_paths(self, run_id: str, run: dict) -> list[Path]:
        directory = resolve_under(self.runs_root, run_id, "items")
        if not directory.is_dir():
            return []
        result = []
        for path in sorted(directory.glob("*.json")):
            validate_item_id(path.stem, set(run["item_ids"]))
            result.append(resolve_under(self.runs_root, run_id, "items", path.name))
        return result

    def _metrics_current(self, run_id: str, run: dict, state: str) -> bool:
        report = resolve_under(self.runs_root, run_id, "metrics.json")
        if state == "running" or self.score_states.get(run_id) in {"pending", "running", "failed"}:
            return False
        if not report.is_file():
            return False
        # B3 atomically writes reports after run/item writes. A resumed or changed
        # run invalidates older reports, including after a server restart.
        sources = [
            resolve_under(self.runs_root, run_id, "run.json"), *self._item_paths(run_id, run),
        ]
        return report.stat().st_mtime_ns >= max(path.stat().st_mtime_ns for path in sources)

    def _read_summary(self, run_id: str) -> dict:
        run = self._read_run(run_id)
        self._item_paths(run_id, run)
        totals = store.compute_totals(self.runs_root, run_id)
        state = store.effective_state(self.runs_root, run_id)
        score_state = self.score_states.get(run_id)
        if score_state not in {"running", "failed"}:
            score_state = "done" if self._metrics_current(run_id, run, state) else "pending"
        return {
            "run_id": run_id, "dataset": run["dataset"], "split": run["split"],
            "n_requested": run.get("n_requested"), "n_items": len(run["item_ids"]),
            "seed": run.get("seed"), "created_at": run["created_at"],
            "finished_at": run.get("finished_at"), "schema_version": run.get("schema_version"),
            "state": state, "score_state": score_state,
            "totals": {"cost_usd": totals["cost_usd"], "failures": totals["failed"]},
            "git_dirty": run.get("git_dirty"),
        }

    async def summary(self, run_id: str) -> dict:
        return await asyncio.to_thread(self._read_summary, run_id)

    def _ensure_idle(self) -> None:
        if self._closing:
            raise ApiError("bad_state", 409, "Server is shutting down.")
        if self._active_handle is not None:
            raise ApiError("run_active", 409, "A run is active.",
                           {"run_id": self._active_handle.run_id})

    def _scoring(self, run_id: str) -> bool:
        task = self._score_tasks.get(run_id)
        return task is not None and not task.done()

    async def _validated_dataset(self, request) -> Dataset:
        dataset = await self.get_dataset(request.dataset)
        if request.split not in {*dataset.meta.split_names(), "all"}:
            raise ApiError("invalid_request", 422, "Unknown split.")
        present, _ = await self.dataset_sizes(dataset)
        if not present:
            raise ApiError("data_missing", 409, "Dataset data is missing.")
        return dataset

    async def _probe(self, stored_version: str | None = None) -> None:
        expected = await asyncio.to_thread(contracts.schema_version)
        result = await engine.probe(self.backend_url, transport=self._probe_transport)
        if not result.reachable:
            raise ApiError("backend_unreachable", 502, "Backend is unavailable.")
        received = result.backend_schema_version
        self.backend_schema_version = received
        mismatch = received is not None and received != expected
        if stored_version is not None and received is not None and received != stored_version:
            expected = stored_version
            mismatch = True
        if mismatch:
            raise ApiError("schema_mismatch", 409, "Backend schema version does not match.",
                           {"expected": expected, "received": received})
        if not result.accepts_version:
            raise ApiError("backend_unreachable", 502, "Backend is unavailable.")

    async def estimate(self, request) -> dict:
        dataset = await self._validated_dataset(request)
        selection = engine.Selection(request.split, request.n, request.seed or 0)
        try:
            result = await asyncio.to_thread(
                estimates.estimate, dataset, selection,
                runs_root=self.runs_root, data_root=self.data_root,
            )
        except DatasetError as exc:
            raise ApiError("invalid_request", 422, "Invalid dataset selection.") from exc
        return asdict(result)

    def _track(self, handle: engine.RunHandle) -> None:
        self._active_handle = handle
        self.score_states[handle.run_id] = "pending"
        self._active_task = asyncio.create_task(self._observe(handle))

    async def start(self, request) -> dict:
        async with self._control_lock:
            self._ensure_idle()
            dataset = await self._validated_dataset(request)
            await self._probe()
            try:
                handle = await engine.start_run_async(
                    dataset, engine.Selection(request.split, request.n, request.seed or 0),
                    base_url=self.backend_url, max_cost_usd=request.max_cost_usd,
                    tags=request.tags, client=self.backend_client, on_finish=None,
                    runs_root=self.runs_root, data_root=self.data_root,
                )
            except DatasetError as exc:
                raise ApiError("invalid_request", 422, "Invalid dataset selection.") from exc
            self._track(handle)
            return {"run_id": handle.run_id}

    async def _observe(self, handle: engine.RunHandle) -> None:
        try:
            await handle.wait()
        except asyncio.CancelledError:
            return
        except Exception as exc:
            self.score_states[handle.run_id] = "failed"
            log_event("run_task_failed", exc_class=type(exc).__name__)
            return
        finally:
            if self._active_handle is handle:
                self._active_handle = None
        if not self._closing:
            self._schedule_score(handle.run_id)

    def _schedule_score(self, run_id: str) -> None:
        self.score_states[run_id] = "running"
        self._score_tasks[run_id] = asyncio.create_task(self._score(run_id))

    async def _score(self, run_id: str) -> None:
        try:
            await asyncio.to_thread(
                scoring.score, run_id, runs_root=self.runs_root,
                datasets_root=self.datasets_root, data_root=self.data_root,
            )
        except Exception as exc:
            self.score_states[run_id] = "failed"
            log_event("score_task_failed", exc_class=type(exc).__name__)
        else:
            self.score_states[run_id] = "done"

    async def abort(self, run_id: str) -> dict:
        async with self._control_lock:
            await asyncio.to_thread(self._read_run, run_id)
            handle = self._active_handle
            if handle is None or handle.run_id != run_id:
                raise ApiError("bad_state", 409, "Run is not active.")
            handle.abort()
            task = self._active_task
        await asyncio.shield(task)
        return await self.summary(run_id)

    async def resume(self, run_id: str) -> dict:
        async with self._control_lock:
            run = await asyncio.to_thread(self._read_run, run_id)
            self._ensure_idle()
            if self._scoring(run_id):
                raise ApiError("bad_state", 409, "Run is being scored.")
            summary = await self.summary(run_id)
            allowed = {"aborted", "aborted_cost", "interrupted", "failed"}
            if summary["state"] not in allowed and not (
                summary["state"] == "finished" and summary["totals"]["failures"] > 0
            ):
                raise ApiError("bad_state", 409, "Run cannot be resumed.")
            dataset = await self.get_dataset(run["dataset"])
            present, _ = await self.dataset_sizes(dataset)
            if not present:
                raise ApiError("data_missing", 409, "Dataset data is missing.")
            await self._probe(run.get("schema_version"))
            try:
                handle = await engine.resume_async(
                    run_id, dataset=dataset, base_url=self.backend_url,
                    client=self.backend_client, on_finish=None,
                    runs_root=self.runs_root, data_root=self.data_root,
                )
            except (engine.ResumeError, store.RunLockedError) as exc:
                raise ApiError("bad_state", 409, "Run cannot be resumed.") from exc
            self._track(handle)
            return await self.summary(run_id)

    async def rescore(self, run_id: str) -> dict:
        async with self._control_lock:
            summary = await self.summary(run_id)
            engine_active = self._active_handle is not None and self._active_handle.run_id == run_id
            if (self._closing or engine_active or summary["state"] == "running"
                    or self._scoring(run_id)):
                raise ApiError("bad_state", 409, "Run cannot be scored now.")
            self._schedule_score(run_id)
            return await self.summary(run_id)

    async def shutdown(self, grace_s: float = 2.0) -> None:
        async with self._control_lock:
            self._closing = True
            handle = self._active_handle
        if handle is not None:
            # Cancellation deliberately leaves the stored state running; releasing
            # the engine lock makes B2 report interrupted, rather than user-aborted.
            handle._task.cancel()
            finished = asyncio.gather(handle._task, return_exceptions=True)
            try:
                await asyncio.wait_for(asyncio.shield(finished), timeout=grace_s)
            except TimeoutError:
                # The grace period is not permission to abandon transport cleanup.
                # Reap the actual engine before its observer or owned HTTP client.
                await asyncio.shield(finished)
            if self._active_task is not None:
                await asyncio.gather(self._active_task, return_exceptions=True)
            # A task cancelled before its first step never enters the driver's
            # try/finally; releasing an already-released RunLock is idempotent.
            await asyncio.to_thread(handle._driver.lock.release)
        tasks = [*self._score_tasks.values(), *self.download_tasks.values()]
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
