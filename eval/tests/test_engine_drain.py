"""A run owns its workers until they stop changing the saved item set."""

import asyncio
import json

import httpx
import pytest
from fakes.fake_backend import FakeBackend

from iaudit_eval import store
from iaudit_eval.client import AuditClient
from iaudit_eval.datasets import load
from iaudit_eval.engine import Selection, resume, start_run
from iaudit_eval.scoring import score


async def test_worker_fault_drains_inflight_before_finish_and_resume(tmp_path, monkeypatch):
    dataset = load("synthetic")
    ids = sorted(it.id for it in dataset.items("all"))
    sibling_started, release, fault = asyncio.Event(), asyncio.Event(), asyncio.Event()
    backend = FakeBackend()
    sent = []

    async def handle(request):
        item_id = json.loads(request.content)["request_id"]
        sent.append(item_id)
        if item_id == ids[1]:
            await sibling_started.wait()
        if item_id == ids[2]:
            sibling_started.set()
            await release.wait()
        return await backend.handle(request)

    write = store.write_item

    def failing_write(root, run_id, item):
        if item["item_id"] == ids[1]:
            fault.set()
            raise OSError("disk fault")
        return write(root, run_id, item)

    monkeypatch.setattr(store, "write_item", failing_write)
    finished = []

    def finish(run_id):
        finished.append({it["item_id"] for it in store.iter_items(tmp_path, run_id)})
        score(run_id, runs_root=tmp_path)

    async with AuditClient("http://fake", transport=httpx.MockTransport(handle)) as client:
        run = start_run(dataset, Selection(split="all"), base_url="http://fake",
                        runs_root=tmp_path, client=client, concurrency=2, on_finish=finish)
        try:
            await asyncio.wait_for(fault.wait(), 2)
            for _ in range(10):
                await asyncio.sleep(0)
            assert store.is_locked(tmp_path, run.run_id)
            assert finished == []
            assert set(sent) == set(ids[:3])
        finally:
            release.set()
            await run.wait()
        assert run.state == "failed"
        assert finished == [{ids[0], ids[2]}]
        assert {it["item_id"] for it in store.iter_items(tmp_path, run.run_id)} == finished[0]
        report = json.loads((tmp_path / run.run_id / "metrics.json").read_text())
        assert report["items"]["not_run"] == 6
        monkeypatch.setattr(store, "write_item", write)
        retried = resume(run.run_id, dataset=dataset, runs_root=tmp_path, client=client,
                         on_finish=None)
        assert await retried.wait() == "finished"
        assert store.load_run(tmp_path, run.run_id)["totals"]["ok"] == 8
        assert len(sent) == 9  # one paid response was lost to the forced disk failure


async def test_cancellation_drains_worker_cleanup_before_unlock(tmp_path):
    dataset = load("synthetic")
    ids = sorted(it.id for it in dataset.items("all"))
    started = {item_id: asyncio.Event() for item_id in ids[1:3]}
    cancelled, release = asyncio.Event(), asyncio.Event()
    backend = FakeBackend()
    sent = []

    async def handle(request):
        item_id = json.loads(request.content)["request_id"]
        sent.append(item_id)
        if item_id in started:
            started[item_id].set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                if item_id == ids[1]:
                    cancelled.set()
                    await release.wait()  # slow transport cleanup must retain run ownership
                raise
        return await backend.handle(request)

    async with AuditClient("http://fake", transport=httpx.MockTransport(handle)) as client:
        run = start_run(dataset, Selection(split="all"), base_url="http://fake",
                        runs_root=tmp_path, client=client, concurrency=2, on_finish=None)
        try:
            await asyncio.wait_for(asyncio.gather(*(e.wait() for e in started.values())), 2)
            run._task.cancel()
            await asyncio.wait_for(cancelled.wait(), 2)
            for _ in range(10):
                await asyncio.sleep(0)
            assert store.is_locked(tmp_path, run.run_id)
            run._task.cancel()
            await asyncio.sleep(0)
            assert store.is_locked(tmp_path, run.run_id)
        finally:
            release.set()
            await asyncio.gather(run._task, return_exceptions=True)
        assert not store.is_locked(tmp_path, run.run_id)
        assert store.effective_state(tmp_path, run.run_id) == "interrupted"
        assert set(sent) == set(ids[:3])
        assert [it["item_id"] for it in store.iter_items(tmp_path, run.run_id)] == ids[:1]


async def test_owned_client_close_error_still_releases_lock(tmp_path):
    class BrokenClose(httpx.MockTransport):
        async def aclose(self):
            raise RuntimeError("close failed")

    backend = FakeBackend()
    run = start_run(load("synthetic"), Selection(split="all"), base_url="http://fake",
                    runs_root=tmp_path, transport=BrokenClose(backend.handle), on_finish=None)
    with pytest.raises(RuntimeError, match="close failed"):
        await run.wait()
    assert not store.is_locked(tmp_path, run.run_id)
    assert store.load_run(tmp_path, run.run_id)["totals"]["ok"] == 8


async def test_cancellation_during_owned_client_close_still_releases_lock(tmp_path):
    request_started, close_started, release = asyncio.Event(), asyncio.Event(), asyncio.Event()

    async def blocked_request(request):
        request_started.set()
        await asyncio.Event().wait()

    class BlockedClose(httpx.MockTransport):
        async def aclose(self):
            close_started.set()
            await release.wait()

    run = start_run(load("synthetic"), Selection(split="all"), base_url="http://fake",
                    runs_root=tmp_path, transport=BlockedClose(blocked_request), on_finish=None)
    try:
        await asyncio.wait_for(request_started.wait(), 2)
        run._task.cancel()
        await asyncio.wait_for(close_started.wait(), 2)
        assert store.is_locked(tmp_path, run.run_id)
        run._task.cancel()
        await asyncio.gather(run._task, return_exceptions=True)
        assert run._task.cancelled()
        assert not store.is_locked(tmp_path, run.run_id)
        assert store.effective_state(tmp_path, run.run_id) == "interrupted"
    finally:
        release.set()
        await asyncio.gather(run._task, return_exceptions=True)
