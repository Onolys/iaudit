"""Shutdown retains the actual engine until cancellation-resistant cleanup finishes."""

import asyncio
import json
import shutil

import httpx
import pytest
from fakes.fake_backend import FakeBackend
from test_dataset_routes import session
from test_run_control import terminal

from iaudit_eval import engine, paths, store
from iaudit_eval.client import AuditClient
from iaudit_eval.datasets import load
from iaudit_eval.server import app as app_module
from iaudit_eval.server.guards import Settings


@pytest.fixture
def roots(tmp_path):
    datasets = tmp_path / "datasets"
    shutil.copytree(paths.datasets_dir() / "eaudit/synthetic", datasets / "eaudit/synthetic")
    return datasets, tmp_path / "data", tmp_path / "runs"


async def test_lifespan_waits_for_engine_cleanup_past_grace_before_closing_client(roots, monkeypatch):
    dataset = load("synthetic", root=roots[0], data_root=roots[1])
    ids = sorted(item.id for item in dataset.items("all"))
    started = {item_id: asyncio.Event() for item_id in ids[1:3]}
    cleaning, release, closed = asyncio.Event(), asyncio.Event(), asyncio.Event()
    backend = FakeBackend()

    async def backend_handler(request):
        if request.method == "POST":
            body = json.loads(request.content)
            item_id = body.get("request_id")
            if item_id in started:
                started[item_id].set()
                try:
                    await asyncio.Event().wait()
                except asyncio.CancelledError:
                    if item_id == ids[1]:
                        cleaning.set()
                        await release.wait()
                    raise
        return await backend.handle(request)

    def owned_client(url):
        client = AuditClient(url, transport=httpx.MockTransport(backend_handler))
        original_close = client.aclose

        async def close():
            closed.set()
            await original_close()

        client.aclose = close
        return client

    # Both the owned client and probe run their real implementations against fakes.
    original_probe = engine.probe

    async def offline_probe(url, **kwargs):
        return await original_probe(url, transport=httpx.MockTransport(backend_handler))

    monkeypatch.setattr(app_module, "AuditClient", owned_client)
    monkeypatch.setattr(engine, "probe", offline_probe)
    app = app_module.create_app(
        Settings(backend_url="http://backend"), datasets_root=roots[0],
        data_root=roots[1], runs_root=roots[2],
    )
    lifespan = app.router.lifespan_context(app)
    await lifespan.__aenter__()
    original_shutdown = app.state.manager.shutdown

    async def short_grace_shutdown():
        await original_shutdown(grace_s=0.01)

    monkeypatch.setattr(app.state.manager, "shutdown", short_grace_shutdown)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://localhost:8100",
    ) as http:
        response = await http.post("/runs", json={"dataset": "synthetic", "split": "all"})
        assert response.status_code == 202
        run_id = response.json()["run_id"]
    handle = app.state.manager._active_handle
    closing = None
    try:
        await asyncio.wait_for(asyncio.gather(*(event.wait() for event in started.values())), 2)
        closing = asyncio.create_task(lifespan.__aexit__(None, None, None))
        await asyncio.wait_for(cleaning.wait(), 2)
        await asyncio.sleep(0.03)  # Exceed the short grace without releasing transport cleanup.
        assert not closing.done()
        assert not closed.is_set()
        assert app.state.manager._active_handle is handle
        assert store.is_locked(roots[2], run_id)
    finally:
        release.set()
        if closing is None:
            closing = asyncio.create_task(lifespan.__aexit__(None, None, None))
        await closing
        await asyncio.gather(handle._task, return_exceptions=True)
    assert closed.is_set()
    assert not store.is_locked(roots[2], run_id)
    assert store.effective_state(roots[2], run_id) == "interrupted"

    monkeypatch.setattr(engine, "probe", original_probe)
    async with session(roots) as (resumed_app, http, _):
        response = await http.post(f"/runs/{run_id}/resume")
        assert response.status_code == 200
        assert (await terminal(resumed_app.state.manager, run_id))["state"] == "finished"
