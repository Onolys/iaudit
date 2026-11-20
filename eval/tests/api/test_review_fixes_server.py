"""Review fixes B-1/B-2/B-3/B-4/B-6 through the manager and HTTP API (fake backend only)."""

import asyncio
import json
import shutil

import httpx
import pytest
from fakes.fake_backend import FakeBackend
from test_dataset_routes import checked, session
from test_run_control import start, terminal

from iaudit_eval import engine, paths, scoring, store
from iaudit_eval.client import AuditClient
from iaudit_eval.datasets import load


@pytest.fixture
def roots(tmp_path):
    datasets = tmp_path / "datasets"
    shutil.copytree(paths.datasets_dir() / "eaudit/synthetic", datasets / "eaudit/synthetic")
    return datasets, tmp_path / "data", tmp_path / "runs"


async def settled(app, http, run_id, want=("done", "failed")):
    async with asyncio.timeout(5):
        while True:
            d = checked(await http.get(f"/runs/{run_id}"), "RunDetail")
            if d["state"] != "running" and d["score_state"] in want:
                return d
            await asyncio.sleep(0.01)


# ---------- B-1 shutdown drain ----------

async def test_shutdown_drains_inflight_within_grace_and_cancels_past_it(roots):
    arrivals = []
    release = asyncio.Event()
    base = FakeBackend()

    async def handler(request):
        if request.method == "POST":
            body = json.loads(request.content)
            if body.get("request_id"):
                arrivals.append(body["request_id"])
                n = len(arrivals)
                if n == 2:
                    await asyncio.sleep(0.15)  # finishes inside the grace period
                elif n >= 3:
                    await release.wait()  # outlives the grace period
        return await base.handle(request)

    async with AuditClient("http://backend", transport=httpx.MockTransport(handler)) as audit:
        from iaudit_eval.server.app import create_app
        from iaudit_eval.server.guards import Settings

        app = create_app(Settings(backend_url="http://backend"), backend_client=audit,
                         datasets_root=roots[0], data_root=roots[1], runs_root=roots[2])
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://localhost:8100",
            ) as http:
                run_id = await start(http, split="all", n=8)
                async with asyncio.timeout(2):
                    while len(arrivals) < 4:
                        await asyncio.sleep(0.005)
                await app.state.manager.shutdown(grace_s=0.4)
        release.set()
    stored = {it["item_id"] for it in store.iter_items(roots[2], run_id)}
    assert len(stored) == 2  # canary + the in-flight item that finished within grace
    assert store.load_run(roots[2], run_id)["state"] == "running"
    assert store.effective_state(roots[2], run_id) == "interrupted"


# ---------- B-2 stale pending ----------

async def finished_unscored_run(roots):
    dataset = load("synthetic", root=roots[0], data_root=roots[1])
    async with AuditClient("http://backend", transport=FakeBackend().transport()) as audit:
        h = engine.start_run(dataset, engine.Selection("dev", 2, 0), base_url="http://backend",
                             client=audit, on_finish=None, runs_root=roots[2],
                             data_root=roots[1])
        await h.wait()
    assert not (roots[2] / h.run_id / "metrics.json").exists()
    return h.run_id


async def test_terminal_run_without_metrics_gets_scored_when_read(roots):
    run_id = await finished_unscored_run(roots)
    async with session(roots) as (app, http, _):
        first = checked(await http.get(f"/runs/{run_id}"), "RunDetail")
        assert first["score_state"] in {"pending", "running", "done"}
        assert (await settled(app, http, run_id))["score_state"] == "done"
        checked(await http.get(f"/runs/{run_id}/metrics"), "MetricsReport")


async def test_interrupted_run_is_scored_when_read(roots):
    run_id = await finished_unscored_run(roots)
    store.update_run(roots[2], run_id, state="running", finished_at=None)
    next((roots[2] / run_id / "items").glob("*.json")).unlink()
    async with session(roots) as (app, http, _):
        detail = await settled(app, http, run_id)
        assert detail["state"] == "interrupted"
        assert detail["score_state"] == "done"


async def test_failed_scoring_is_not_rescheduled_for_the_same_revision(roots, monkeypatch):
    run_id = await finished_unscored_run(roots)
    calls = []

    def fail(*args, **kwargs):
        calls.append(1)
        raise RuntimeError("boom")

    monkeypatch.setattr(scoring, "score", fail)
    async with session(roots) as (app, http, _):
        assert (await settled(app, http, run_id))["score_state"] == "failed"
        for _ in range(5):
            await http.get(f"/runs/{run_id}")
            await http.get("/runs")
            await asyncio.sleep(0.02)
        assert len(calls) == 1


# ---------- B-3 refused resume ----------

async def test_refused_resume_is_surfaced_and_keeps_metrics(roots):
    backend = FakeBackend()
    async with session(roots, backend) as (app, http, _):
        run_id = await start(http, n=3)
        await terminal(app.state.manager, run_id)
        store.update_run(roots[2], run_id, state="aborted")
        next((roots[2] / run_id / "items").glob("*.json")).unlink()
        backend.mode = "changed_models"
        checked(await http.post(f"/runs/{run_id}/resume"), "RunSummary")
        async with asyncio.timeout(5):
            while True:
                d = checked(await http.get(f"/runs/{run_id}"), "RunDetail")
                if d["state"] != "running" and d.get("resume_refusal"):
                    break
                await asyncio.sleep(0.01)
        assert d["resume_refusal"]["kind"] == "fingerprint_changed"
        assert d["resume_refusal"]["changes"][0]["field"] == "models"
        d = await settled(app, http, run_id)
        assert d["score_state"] == "done"  # not "failed": scoring never ran for the refusal
        assert d["state"] == "aborted"
        # a successful resume clears the last refusal
        backend.mode = "ok"
        checked(await http.post(f"/runs/{run_id}/resume"), "RunSummary")
        done = await terminal(app.state.manager, run_id)
        assert done["state"] == "finished"
        assert checked(await http.get(f"/runs/{run_id}"), "RunDetail").get("resume_refusal") is None
