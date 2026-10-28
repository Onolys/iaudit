"""Offline HTTP coverage of health, dataset discovery and threaded downloads."""

import asyncio
import json
import shutil
import threading
from contextlib import asynccontextmanager

import httpx
import pytest
from fakes.fake_backend import FakeBackend
from jsonschema import Draft202012Validator

from iaudit_eval import paths
from iaudit_eval.client import AuditClient
from iaudit_eval.server.app import create_app
from iaudit_eval.server.guards import Settings


@pytest.fixture
def roots(tmp_path):
    datasets = tmp_path / "datasets"
    shutil.copytree(paths.datasets_dir() / "eaudit/synthetic", datasets / "eaudit/synthetic")
    return datasets, tmp_path / "data", tmp_path / "runs"


@asynccontextmanager
async def session(roots, backend=None):
    datasets, data, runs = roots
    backend = backend or FakeBackend()
    async with AuditClient("http://backend", transport=backend.transport(), timeout_s=0.1) as audit:
        app = create_app(
            Settings(backend_url="http://backend"), backend_client=audit,
            datasets_root=datasets, data_root=data, runs_root=runs,
        )
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://localhost:8100",
            ) as http:
                yield app, http, backend


def checked(response, definition, status=200):
    assert response.status_code == status, response.text
    schema = json.loads((paths.repo_root() / "eval/api/eval-api.schema.json").read_text())
    if definition.endswith("[]"):
        schema.update(type="array", items={"$ref": f"#/$defs/{definition[:-2]}"})
    else:
        schema["$ref"] = f"#/$defs/{definition}"
    body = response.json()
    Draft202012Validator(schema).validate(body)
    return body


async def test_health_probes_fake_backend_without_audit_work(roots):
    async with session(roots) as (_, http, backend):
        body = checked(await http.get("/health"), "Health")
        assert body["status"] == "ok"
        assert body["eval_api_version"]
        assert body["backend"] == {"url": "http://backend", "reachable": True, "schema_version": None}
        assert backend.count == 0
        assert backend.audit_work == 0


@pytest.mark.parametrize("failure", ["connect", "timeout", "503"])
async def test_health_reports_unreachable_backend(roots, failure):
    class Unreachable(FakeBackend):
        async def handle(self, request):
            assert request.method == "GET" and request.url.path == "/healthz"
            if failure == "503":
                return httpx.Response(503)
            if failure == "connect":
                raise httpx.ConnectError("offline", request=request)
            raise httpx.ReadTimeout("offline", request=request)

    async with session(roots, Unreachable()) as (_, http, _):
        body = checked(await http.get("/health"), "Health")
        assert body["backend"]["reachable"] is False
        assert body["backend"].get("schema_version") is None


async def test_dataset_list_and_metadata_use_injected_roots(roots, monkeypatch, tmp_path):
    # A default registry lookup would see an empty directory and lose our synthetic dataset.
    monkeypatch.setenv("IAUDIT_EVAL_HOME", str(tmp_path / "wrong-default"))
    async with session(roots) as (_, http, _):
        datasets = checked(await http.get("/datasets"), "DatasetSummary[]")
        assert len(datasets) == 1
        assert datasets[0]["name"] == "synthetic"
        assert datasets[0]["product"] == "eaudit"
        assert datasets[0]["data_present"] is True
        assert datasets[0]["splits"] == [{"name": "dev", "size": 15}, {"name": "test", "size": 5}]
        meta = checked(await http.get("/datasets/synthetic"), "DatasetMeta")
        assert meta["product"] == "eaudit"
        assert meta["default_split"] == "dev"
        assert meta["license"]["name"] == "CC0-1.0"
        assert meta["splits"][0]["size"] == 15
        assert meta["splits"][0]["description"]


@pytest.mark.parametrize("method,path", [
    ("GET", "/datasets/missing"), ("POST", "/datasets/missing/download"),
    ("GET", "/datasets/missing/download"), ("GET", "/datasets/%2e%2e"),
])
async def test_unknown_dataset_is_schema_valid_404(roots, method, path):
    async with session(roots) as (_, http, _):
        error = checked(await http.request(method, path), "ErrorResponse", 404)
        assert error["error"]["code"] == "not_found"


def downloadable(roots):
    datasets, data, _ = roots
    folder = datasets / "eaudit/local"
    folder.mkdir()
    (folder / "metadata.json").write_text(json.dumps({
        "name": "local", "product": "eaudit", "title": "Offline download", "data_required": True,
        "splits": [{"name": "test", "description": "Local fixture"}], "default_split": "test",
    }))
    (folder / "adapter.py").write_text('''
import hashlib
import threading
from iaudit_eval.datasets import Item
from iaudit_eval.download import FileRecord

class Adapter:
    def __init__(self, data_dir):
        self.data_dir = data_dir
        self.started = threading.Event()
        self.release = threading.Event()
        self.calls = 0
        self.fail = False
        self.thread_id = None

    def items(self, split):
        if not (self.data_dir / "fixture.txt").exists():
            raise RuntimeError("items must not be read until data exists")
        return [Item("local-item", "doc", "test", {}, {})]

    def download(self, directory, progress):
        self.calls += 1
        self.thread_id = threading.get_ident()
        self.started.set()
        if not self.release.wait(5):
            raise TimeoutError("test did not release download")
        if self.fail:
            raise ValueError("offline failure")
        content = b"offline fixture"
        (directory / "fixture.txt").write_bytes(content)
        return [FileRecord("local", "fixture.txt", hashlib.sha256(content).hexdigest(),
                           len(content), "2026-10-21T00:00:00Z")]

def create(data_dir):
    return Adapter(data_dir)
''')
    return data / "local"


async def wait_status(http, wanted):
    async with asyncio.timeout(3):
        while True:
            body = checked(await http.get("/datasets/local/download"), "DownloadStatus")
            if body["status"] == wanted:
                return body
            await asyncio.sleep(0.01)


async def test_download_states_single_task_and_event_loop_remains_responsive(roots):
    location = downloadable(roots)
    async with session(roots) as (app, http, _):
        datasets = checked(await http.get("/datasets"), "DatasetSummary[]")
        local = next(d for d in datasets if d["name"] == "local")
        assert local["data_present"] is False
        assert local["splits"] == [{"name": "test", "size": None}]
        meta = checked(await http.get("/datasets/local"), "DatasetMeta")
        assert meta["splits"][0]["size"] is None
        assert checked(await http.get("/datasets/local/download"), "DownloadStatus")["status"] == "not_downloaded"
        body = checked(await http.post("/datasets/local/download"), "DownloadStatus", 202)
        assert body["status"] == "downloading"
        await wait_status(http, "downloading")
        dataset = await app.state.manager.get_dataset("local")
        adapter = dataset.adapter
        try:
            async with asyncio.timeout(2):
                while not adapter.started.is_set():
                    await asyncio.sleep(0.01)
            assert adapter.thread_id != threading.get_ident()
            second = checked(await http.post("/datasets/local/download"), "DownloadStatus", 202)
            assert second["status"] == "downloading"
            assert adapter.calls == 1
            checked(await http.get("/health"), "Health")
        finally:
            adapter.release.set()
        ready = await wait_status(http, "ready")
        assert ready["files"][0]["filename"] == "fixture.txt"
        assert (location / "fixture.txt").read_bytes() == b"offline fixture"
        datasets = checked(await http.get("/datasets"), "DatasetSummary[]")
        local = next(d for d in datasets if d["name"] == "local")
        assert local["data_present"] is True
        assert local["splits"] == [{"name": "test", "size": 1}]


async def test_failed_download_is_visible_and_retryable(roots):
    downloadable(roots)
    async with session(roots) as (app, http, _):
        await http.get("/datasets/local")
        adapter = (await app.state.manager.get_dataset("local")).adapter
        adapter.fail = True
        adapter.release.set()
        checked(await http.post("/datasets/local/download"), "DownloadStatus", 202)
        failed = await wait_status(http, "failed")
        assert failed["error"] == "Download failed."
        adapter.fail = False
        checked(await http.post("/datasets/local/download"), "DownloadStatus", 202)
        await wait_status(http, "ready")
        assert adapter.calls == 2


async def test_download_outlives_request_client(roots):
    downloadable(roots)
    async with session(roots) as (app, http, _):
        await http.get("/datasets/local")
        adapter = (await app.state.manager.get_dataset("local")).adapter
        try:
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://localhost:8100",
            ) as temporary:
                checked(await temporary.post("/datasets/local/download"), "DownloadStatus", 202)
            assert checked(await http.get("/datasets/local/download"), "DownloadStatus")["status"] == "downloading"
        finally:
            adapter.release.set()
        await wait_status(http, "ready")


@pytest.mark.parametrize("filename", ["metadata.json", "adapter.py"])
async def test_dataset_file_symlink_cannot_escape_root(roots, tmp_path, filename):
    datasets, _, _ = roots
    source = datasets / "eaudit/synthetic" / filename
    outside = tmp_path / ("outside-" + filename)
    source.replace(outside)
    source.symlink_to(outside)
    async with session(roots) as (_, http, _):
        error = checked(await http.get("/datasets/synthetic"), "ErrorResponse", 404)
        assert error["error"]["code"] == "not_found"


async def test_ready_status_with_deleted_data_reports_missing_sizes(roots):
    location = downloadable(roots)
    async with session(roots) as (app, http, _):
        await http.get("/datasets/local")
        adapter = (await app.state.manager.get_dataset("local")).adapter
        adapter.release.set()
        checked(await http.post("/datasets/local/download"), "DownloadStatus", 202)
        await wait_status(http, "ready")
        (location / "fixture.txt").unlink()
        datasets = checked(await http.get("/datasets"), "DatasetSummary[]")
        local = next(d for d in datasets if d["name"] == "local")
        assert local["data_present"] is False
        assert local["splits"][0]["size"] is None
