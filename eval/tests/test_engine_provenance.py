"""Download provenance is recorded before dispatch using the injected dataset data."""

import hashlib
import json
import threading
from dataclasses import replace

from fakes.fake_backend import FakeBackend
from fakes.synthetic import engine_dataset

from iaudit_eval import download, engine, store
from iaudit_eval.client import AuditClient
from iaudit_eval.engine import Selection, resume_async, start_run_async

UPSTREAM = "downloaded file 'source.txt' changed upstream since first recorded"
TAMPERED = "downloaded file 'source.txt' changed since it was recorded"


def _dataset_and_data(tmp_path):
    dataset = engine_dataset()
    dataset = replace(dataset, meta=replace(dataset.meta, data_required=True))
    data = tmp_path / "injected-data"
    directory = data / dataset.meta.name
    directory.mkdir(parents=True)
    (directory / "source.txt").write_bytes(b"original")
    status = {"status": "ready", "files": [{
        "id": "source", "filename": "source.txt",
        "sha256": hashlib.sha256(b"original").hexdigest(),
    }], "warnings": []}
    (directory / "download.json").write_text(json.dumps(status))
    return dataset, data, directory, status


def _tamper(directory, status):
    (directory / "source.txt").write_bytes(b"modified")
    status["warnings"] = [UPSTREAM, UPSTREAM]
    (directory / "download.json").write_text(json.dumps(status))


def _assert_hashes_off_loop(monkeypatch):
    main_thread = threading.get_ident()
    original = download._hash_file

    def hash_file(path):
        assert threading.get_ident() != main_thread, "hashing blocked the caller loop"
        return original(path)

    monkeypatch.setattr(download, "_hash_file", hash_file)


async def test_start_records_download_warnings_before_first_request(tmp_path, monkeypatch):
    dataset, data, directory, status = _dataset_and_data(tmp_path)
    _tamper(directory, status)
    _assert_hashes_off_loop(monkeypatch)
    runs = tmp_path / "runs"
    warnings_at_dispatch = []

    class Backend(FakeBackend):
        async def handle(self, request):
            warnings_at_dispatch.append(store.list_runs(runs)[0]["warnings"])
            return await super().handle(request)

    backend = Backend()
    async with AuditClient("http://fake", transport=backend.transport()) as client:
        handle = await start_run_async(dataset, Selection(split="all"), base_url="http://fake",
                                       runs_root=runs, data_root=data, client=client,
                                       on_finish=None)
        assert await handle.wait() == "finished"
    assert backend.count == 8
    assert all(warnings == [UPSTREAM, TAMPERED] for warnings in warnings_at_dispatch)
    assert store.load_run(runs, handle.run_id)["warnings"] == [UPSTREAM, TAMPERED]


async def test_resume_adds_provenance_without_losing_or_duplicating_warnings(tmp_path, monkeypatch):
    dataset, data, directory, status = _dataset_and_data(tmp_path)
    _assert_hashes_off_loop(monkeypatch)
    runs = tmp_path / "runs"
    backend = FakeBackend("500", script=["ok"])
    async with AuditClient("http://fake", transport=backend.transport()) as client:
        handle = await start_run_async(dataset, Selection(split="all"), base_url="http://fake",
                                       runs_root=runs, data_root=data, client=client,
                                       on_finish=None)
        await handle.wait()
    preserved = ["existing provenance warning", "resume mixed fingerprints (allow_mixed)"]
    store.update_run(runs, handle.run_id, warnings=preserved)
    _tamper(directory, status)
    monkeypatch.setattr(engine, "capture_git", lambda: {
        "git_commit": "f" * 40, "git_dirty": False, "git_diff_sha256": "new-diff",
    })
    warnings_at_dispatch = []

    class Backend(FakeBackend):
        async def handle(self, request):
            warnings_at_dispatch.append(store.load_run(runs, handle.run_id)["warnings"])
            return await super().handle(request)

    backend = Backend()
    async with AuditClient("http://fake", transport=backend.transport()) as client:
        for _ in range(2):
            resumed = await resume_async(handle.run_id, dataset=dataset, runs_root=runs,
                                         data_root=data, client=client, on_finish=None)
            assert await resumed.wait() == "finished"
    warnings = store.load_run(runs, handle.run_id)["warnings"]
    assert all(w in warnings for w in preserved)
    assert warnings.count(UPSTREAM) == warnings.count(TAMPERED) == 1
    assert any("git commit or dirty state changed" in w for w in warnings)
    assert len(warnings) == len(set(warnings))
    assert warnings_at_dispatch and all(w == warnings for w in warnings_at_dispatch)
    assert backend.count == 7  # second resume does not re-send successful items
