"""Async server integration keeps synchronous preparation off the caller's loop."""

import asyncio
import threading

import pytest
from fakes.fake_backend import FakeBackend

from iaudit_eval import engine, store
from iaudit_eval.client import AuditClient
from iaudit_eval.datasets import load


def entrypoint(name):
    result = getattr(engine, name, None)
    assert callable(result), f"missing async engine entrypoint: {name}"
    return result


async def test_async_start_keeps_loop_responsive_during_preparation(tmp_path, monkeypatch):
    start = entrypoint("start_run_async")
    dataset = load("synthetic")
    original = dataset.adapter.items
    entered, release = threading.Event(), threading.Event()
    main_thread = threading.get_ident()
    thread_ids = []

    def blocked_items(split):
        thread_ids.append(threading.get_ident())
        entered.set()
        assert release.wait(3)
        return original(split)

    monkeypatch.setattr(dataset.adapter, "items", blocked_items)
    backend = FakeBackend()
    async with AuditClient("http://backend", transport=backend.transport()) as client:
        task = asyncio.create_task(start(dataset, engine.Selection(split="dev", n=1),
                                         base_url="http://backend", runs_root=tmp_path,
                                         client=client, on_finish=None))
        try:
            async with asyncio.timeout(2):
                while not entered.is_set():
                    await asyncio.sleep(0.001)
            assert not task.done()
            assert all(tid != main_thread for tid in thread_ids)
        finally:
            release.set()
        handle = await task
        assert await handle.wait() == "finished"
        assert len(list(store.iter_items(tmp_path, handle.run_id))) == 1


async def test_cancel_during_preparation_releases_created_run_lock(tmp_path, monkeypatch):
    start = entrypoint("start_run_async")
    entered, release = threading.Event(), threading.Event()
    acquire = store.RunLock.acquire

    def blocking_acquire(lock):
        result = acquire(lock)
        entered.set()
        assert release.wait(3)
        return result

    monkeypatch.setattr(store.RunLock, "acquire", blocking_acquire)
    backend = FakeBackend()
    async with AuditClient("http://backend", transport=backend.transport()) as client:
        task = asyncio.create_task(start(load("synthetic"), engine.Selection(split="dev", n=1),
                                         base_url="http://backend", runs_root=tmp_path,
                                         client=client, on_finish=None))
        try:
            async with asyncio.timeout(2):
                while not entered.is_set():
                    await asyncio.sleep(0.001)
            task.cancel()
            await asyncio.sleep(0)
        finally:
            release.set()
        with pytest.raises(asyncio.CancelledError):
            await task
        monkeypatch.setattr(store.RunLock, "acquire", acquire)
        runs = store.list_runs(tmp_path)
        assert len(runs) == 1
        assert store.effective_state(tmp_path, runs[0]["run_id"]) == "interrupted"
        assert not store.is_locked(tmp_path, runs[0]["run_id"])
        assert backend.count == 0


async def test_async_resume_preserves_existing_public_semantics(tmp_path):
    resume = entrypoint("resume_async")
    backend = FakeBackend()
    dataset = load("synthetic")
    async with AuditClient("http://backend", transport=backend.transport()) as client:
        handle = engine.start_run(dataset, engine.Selection(split="dev", n=1),
                                  base_url="http://backend", runs_root=tmp_path,
                                  client=client, on_finish=None)
        await handle.wait()
        resumed = await resume(handle.run_id, dataset=dataset, runs_root=tmp_path,
                               client=client, on_finish=None)
        assert await resumed.wait() == "finished"
        assert backend.count == 1
        assert len(store.load_run(tmp_path, handle.run_id)["resumes"]) == 1
