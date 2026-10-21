"""Server-owned background work and dataset access with explicitly configured roots."""

from __future__ import annotations

import asyncio
from pathlib import Path

from iaudit_eval import download
from iaudit_eval.datasets import Dataset, load
from iaudit_eval.log import log_event
from iaudit_eval.server.guards import (
    ApiError,
    not_found,
    resolve_under,
    validate_dataset_id,
)


class RunManager:
    """Own downloads independently of HTTP clients; run control extends this manager."""

    def __init__(self, *, datasets_root: Path, data_root: Path, runs_root: Path):
        self.datasets_root = datasets_root
        self.data_root = data_root
        self.runs_root = runs_root
        self._datasets: dict[str, Dataset] = {}
        self._dataset_lock = asyncio.Lock()
        self._download_lock = asyncio.Lock()
        self.download_tasks: dict[str, asyncio.Task] = {}
        self._download_errors: dict[str, dict] = {}

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
            return self._download_errors[name]
        task = self.download_tasks.get(name)
        if task is not None and not task.done():
            return {"status": "downloading", "files": []}
        return await asyncio.to_thread(download.status, dataset, data_root=self.data_root)

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

    async def shutdown(self) -> None:
        if self.download_tasks:
            await asyncio.gather(*self.download_tasks.values(), return_exceptions=True)
