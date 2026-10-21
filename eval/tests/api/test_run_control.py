"""Zero-spend API run controls over B2's fake backend and synthetic dataset."""

import asyncio
import json
import shutil
import threading

import httpx
import pytest
from fakes.fake_backend import FakeBackend
from test_dataset_routes import checked, downloadable, session

from iaudit_eval import contracts, paths, scoring, store


@pytest.fixture
def roots(tmp_path):
    datasets = tmp_path / "datasets"
    shutil.copytree(paths.datasets_dir() / "synthetic", datasets / "synthetic")
    return datasets, tmp_path / "data", tmp_path / "runs"


async def terminal(manager, run_id):
    async with asyncio.timeout(5):
        while True:
            result = await manager.summary(run_id)
            if result["state"] != "running" and result["score_state"] in {"done", "failed"}:
                return result
            await asyncio.sleep(0.005)


async def start(http, **extra):
    return checked(await http.post("/runs", json={
        "dataset": "synthetic", "split": "dev", "n": 2, **extra,
    }), "RunCreated", 202)["run_id"]


async def test_estimate_start_auto_score_and_disconnected_client(roots):
    async with session(roots) as (app, http, backend):
        estimate = checked(await http.post("/runs/estimate", json={
            "dataset": "synthetic", "split": "dev", "n": 2,
        }), "Estimate")
        assert estimate == {"basis": "none", "n_items": 2, "est_input_tokens": None,
                            "est_output_tokens": None, "est_cost_usd": None, "rough": True,
                            "note": "No prior runs of this dataset reported usage: run a small N first (about 5 items)."}
        assert backend.count == 0
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://localhost:8100",
        ) as temporary:
            run_id = await start(temporary, tags={"contamination": "none"})
        result = await terminal(app.state.manager, run_id)
        assert result["state"] == "finished"
        assert result["score_state"] == "done"
        assert result["totals"] == {"cost_usd": 0.02, "failures": 0}
        run = store.load_run(roots[2], run_id)
        assert run["tags"] == {"contamination": "none"}
        assert run["seed"] == 0
        report = json.loads((roots[2] / run_id / "metrics.json").read_text())
        assert report["items"]["selected"] == 2
        assert backend.audit_work == 2
        assert backend.count == 3  # One zero-spend invalid-body probe plus two real fake calls.
        prior = checked(await http.post("/runs/estimate", json={
            "dataset": "synthetic", "split": "dev", "n": 2,
        }), "Estimate")
        assert prior["basis"] == "prior_runs"
        assert prior["est_cost_usd"] is not None


async def test_concurrent_starts_hold_reservation_through_probe(roots):
    class SlowProbe(FakeBackend):
        async def handle(self, request):
            if request.url.path == "/healthz":
                await asyncio.sleep(0.03)
            return await super().handle(request)

    async with session(roots, SlowProbe(delay=0.04)) as (app, http, _):
        responses = await asyncio.gather(*[
            http.post("/runs", json={"dataset": "synthetic", "split": "dev", "n": 6})
            for _ in range(2)
        ])
        created = next(r for r in responses if r.status_code == 202)
        run_id = checked(created, "RunCreated", 202)["run_id"]
        conflict = next(r for r in responses if r.status_code == 409)
        error = checked(conflict, "ErrorResponse", 409)["error"]
        assert error["code"] == "run_active"
        assert error["detail"]["run_id"] == run_id
        assert len(store.list_runs(roots[2])) == 1
        await terminal(app.state.manager, run_id)


@pytest.mark.parametrize("mode,expected_status,expected_code", [
    ("down", 502, "backend_unreachable"), ("version", 409, "schema_mismatch"),
    ("503", 502, "backend_unreachable"), ("bad_probe", 502, "backend_unreachable"),
])
async def test_probe_failure_creates_no_run_and_spends_nothing(roots, mode, expected_status, expected_code):
    class ProbeBackend(FakeBackend):
        async def handle(self, request):
            if mode == "bad_probe" and request.method == "POST":
                return httpx.Response(503, text="SECRET-UNAVAILABLE")
            if mode == "down":
                raise httpx.ConnectError("SECRET-TRANSPORT", request=request)
            return await super().handle(request)

    backend = ProbeBackend(supported_version="9.0.0" if mode == "version" else None,
                           mode="503" if mode == "503" else "ok")
    async with session(roots, backend) as (_, http, _):
        response = await http.post("/runs", json={"dataset": "synthetic", "split": "dev"})
        error = checked(response, "ErrorResponse", expected_status)["error"]
        assert error["code"] == expected_code
        assert "SECRET-TRANSPORT" not in response.text
        assert "SECRET-UNAVAILABLE" not in response.text
        assert not roots[2].exists()
        assert backend.audit_work == 0
        if mode == "version":
            assert contracts.schema_version() in error["detail"].values()
            assert "9.0.0" in error["detail"].values()


@pytest.mark.parametrize("extra", [{"n": 0}, {"split": "unknown"}, {"max_cost_usd": -1}])
async def test_invalid_run_requests_fail_before_probe(roots, extra):
    async with session(roots) as (_, http, backend):
        response = await http.post("/runs", json={"dataset": "synthetic", "split": "dev", **extra})
        assert checked(response, "ErrorResponse", 422)["error"]["code"] == "invalid_request"
        assert backend.count == 0
        assert not roots[2].exists()


async def test_missing_data_refused_before_probe_or_run_creation(roots):
    downloadable(roots)
    async with session(roots) as (_, http, backend):
        response = await http.post("/runs", json={"dataset": "local", "split": "test"})
        assert checked(response, "ErrorResponse", 409)["error"]["code"] == "data_missing"
        assert not roots[2].exists()
        assert backend.count == 0


async def test_abort_and_resume(roots):
    async with session(roots, FakeBackend(delay=0.04)) as (app, http, backend):
        run_id = await start(http, n=6)
        async with asyncio.timeout(2):
            while backend.in_flight == 0:
                await asyncio.sleep(0.001)
        aborted = checked(await http.post(f"/runs/{run_id}/abort"), "RunSummary")
        assert aborted["state"] == "aborted"
        await terminal(app.state.manager, run_id)
        resumed = checked(await http.post(f"/runs/{run_id}/resume"), "RunSummary")
        assert resumed["state"] == "running"
        assert (await terminal(app.state.manager, run_id))["state"] == "finished"
        error = checked(await http.post(f"/runs/{run_id}/resume"), "ErrorResponse", 409)["error"]
        assert error["code"] == "bad_state"


async def test_cap_aborts_and_resume_makes_progress(roots):
    async with session(roots) as (app, http, _):
        run_id = await start(http, max_cost_usd=0.005)
        assert (await terminal(app.state.manager, run_id))["state"] == "aborted_cost"
        assert len(list(store.iter_items(roots[2], run_id))) == 1
        checked(await http.post(f"/runs/{run_id}/resume"), "RunSummary")
        await terminal(app.state.manager, run_id)
        assert len(list(store.iter_items(roots[2], run_id))) == 2


async def test_cap_with_missing_cost_fails_closed(roots):
    async with session(roots, FakeBackend("missing_cost")) as (app, http, backend):
        run_id = await start(http, max_cost_usd=1)
        result = await terminal(app.state.manager, run_id)
        assert result["state"] == "failed"
        assert result["totals"]["cost_usd"] is None
        assert store.load_run(roots[2], run_id)["error"]["kind"] == "cost_missing"
        assert backend.audit_work == 1


async def test_unlocked_running_run_is_interrupted_and_resumable(roots):
    async with session(roots) as (app, http, _):
        run_id = await start(http)
        await terminal(app.state.manager, run_id)
    store.update_run(roots[2], run_id, state="running", finished_at=None)
    item = next((roots[2] / run_id / "items").glob("*.json"))
    item.unlink()
    async with session(roots) as (app, http, _):
        assert (await app.state.manager.summary(run_id))["state"] == "interrupted"
        assert checked(await http.post(f"/runs/{run_id}/resume"), "RunSummary")["state"] == "running"
        assert (await terminal(app.state.manager, run_id))["state"] == "finished"


async def test_rescore_and_resume_exclude_each_other(roots, monkeypatch):
    async with session(roots) as (app, http, _):
        run_id = await start(http)
        await terminal(app.state.manager, run_id)
        store.update_run(roots[2], run_id, state="aborted")
        original = scoring.score
        entered, release = threading.Event(), threading.Event()

        def blocked_score(*args, **kwargs):
            entered.set()
            assert release.wait(3)
            return original(*args, **kwargs)

        monkeypatch.setattr(scoring, "score", blocked_score)
        try:
            rescoring = checked(await http.post(f"/runs/{run_id}/rescore"), "RunSummary", 202)
            assert rescoring["score_state"] == "running"
            async with asyncio.timeout(2):
                while not entered.is_set():
                    await asyncio.sleep(0.001)
            for action in ("resume", "rescore"):
                response = await http.post(f"/runs/{run_id}/{action}")
                assert checked(response, "ErrorResponse", 409)["error"]["code"] == "bad_state"
            # A different run can execute while this run's rescore owns only its outputs.
            next_id = await start(http, n=1)
        finally:
            release.set()
        await terminal(app.state.manager, run_id)
        await terminal(app.state.manager, next_id)


async def test_rescore_refused_during_engine_run(roots):
    async with session(roots, FakeBackend(delay=0.04)) as (app, http, _):
        run_id = await start(http, n=6)
        response = await http.post(f"/runs/{run_id}/rescore")
        assert checked(response, "ErrorResponse", 409)["error"]["code"] == "bad_state"
        await terminal(app.state.manager, run_id)


async def test_scoring_failure_reported_without_exception_text(roots, monkeypatch, caplog):
    def fail_score(*args, **kwargs):
        raise RuntimeError("SECRET-SCORING-FAILURE")

    monkeypatch.setattr(scoring, "score", fail_score)
    async with session(roots) as (app, http, _):
        run_id = await start(http)
        result = await terminal(app.state.manager, run_id)
        assert result["state"] == "finished"
        assert result["score_state"] == "failed"
        assert "SECRET-SCORING-FAILURE" not in caplog.text


async def test_shutdown_releases_lock_and_keeps_run_interrupted(roots):
    async with session(roots, FakeBackend(delay=0.04)) as (_, http, _):
        run_id = await start(http, n=6)
    assert store.effective_state(roots[2], run_id) == "interrupted"
    assert not store.is_locked(roots[2], run_id)


async def test_invalid_run_ids_and_unknown_runs_have_safe_errors(roots):
    async with session(roots) as (_, http, _):
        for run_id in ("bad", "20260101T000000Z-synthetic-ab12cd"):
            for action in ("abort", "resume", "rescore"):
                response = await http.post(f"/runs/{run_id}/{action}")
                assert checked(response, "ErrorResponse", 404)["error"]["code"] == "not_found"


async def test_shutdown_before_engine_first_step_releases_prepared_lock(roots):
    from iaudit_eval.server.models import RunRequest

    async with session(roots) as (app, _, _):
        created = await app.state.manager.start(RunRequest(dataset="synthetic", split="dev"))
        # No yield between receiving the newly spawned handle and shutdown.
        await app.state.manager.shutdown()
        assert not store.is_locked(roots[2], created["run_id"])
        assert store.effective_state(roots[2], created["run_id"]) == "interrupted"


async def test_rescore_refused_until_active_engine_finalizer_finishes(roots):
    async with session(roots, FakeBackend(delay=0.04)) as (app, http, _):
        run_id = await start(http, n=1)
        entered, release = asyncio.Event(), asyncio.Event()

        async def finalizer(_run_id):
            entered.set()
            await release.wait()

        app.state.manager._active_handle._driver.on_finish = finalizer
        try:
            await asyncio.wait_for(entered.wait(), timeout=2)
            assert store.effective_state(roots[2], run_id) == "finished"
            response = await http.post(f"/runs/{run_id}/rescore")
            assert checked(response, "ErrorResponse", 409)["error"]["code"] == "bad_state"
        finally:
            release.set()
        await terminal(app.state.manager, run_id)


async def test_shutdown_serializes_with_run_preparation(roots, monkeypatch):
    from iaudit_eval.server.models import RunRequest

    async with session(roots, FakeBackend(delay=0.04)) as (app, _, _):
        manager = app.state.manager
        dataset = await manager.get_dataset("synthetic")
        original = dataset.adapter.items
        entered, release = threading.Event(), threading.Event()

        def blocked_items(split):
            entered.set()
            assert release.wait(3)
            return original(split)

        monkeypatch.setattr(dataset.adapter, "items", blocked_items)
        starting = asyncio.create_task(manager.start(RunRequest(dataset="synthetic", split="dev")))
        try:
            async with asyncio.timeout(2):
                while not entered.is_set():
                    await asyncio.sleep(0.001)
            closing = asyncio.create_task(manager.shutdown())
            await asyncio.sleep(0.01)
        finally:
            release.set()
        created = await starting
        await closing
        assert (await manager.summary(created["run_id"]))["state"] == "interrupted"
        assert not store.is_locked(roots[2], created["run_id"])
