"""Run read contracts use real stored outputs and perform no writes or live I/O."""

import asyncio
import json
import shutil
import threading

import pytest
from fakes.fake_backend import FakeBackend
from test_dataset_routes import checked, session
from test_run_control import start, terminal

from iaudit_eval import paths, scoring, store


@pytest.fixture
def roots(tmp_path):
    datasets = tmp_path / "datasets"
    shutil.copytree(paths.datasets_dir() / "eaudit/synthetic", datasets / "eaudit/synthetic")
    return datasets, tmp_path / "data", tmp_path / "runs"


async def test_run_list_detail_and_metrics_match_committed_contract(roots):
    async with session(roots) as (app, http, _):
        assert checked(await http.get("/runs"), "RunSummary[]") == []
        older = await start(http, tags={"contamination": "possible"})
        await terminal(app.state.manager, older)
        newer = await start(http, n=1)
        await terminal(app.state.manager, newer)
        runs = checked(await http.get("/runs"), "RunSummary[]")
        assert [run["run_id"] for run in runs] == [newer, older]
        detail = checked(await http.get(f"/runs/{older}"), "RunDetail")
        assert detail["progress"] == {"done": 2, "total": 2, "failures": 0, "cost_usd": 0.02}
        assert detail["run_info"]["tags"] == {"contamination": "possible"}
        assert detail["run_info"]["fingerprint"]["models"]
        assert detail["run_info"]["fingerprint"]["prompt_hashes"]
        report = checked(await http.get(f"/runs/{older}/metrics"), "MetricsReport")
        assert report["run_id"] == older
        assert report["items"]["selected"] == 2


async def test_item_filters_pagination_and_failure_detail(roots):
    backend = FakeBackend(script=["ok", "ok", "500", "ok"])
    async with session(roots, backend) as (app, http, _):
        run_id = await start(http, n=3)
        await terminal(app.state.manager, run_id)
        all_items = checked(await http.get(f"/runs/{run_id}/items"), "ItemPage")
        assert all_items["total"] == 3
        assert len(all_items["items"]) == 3
        mismatch = checked(await http.get(f"/runs/{run_id}/items?filter=mismatch"), "ItemPage")
        assert mismatch["total"] == 1
        assert mismatch["items"][0]["match"] is False
        failed = checked(await http.get(f"/runs/{run_id}/items?filter=failed"), "ItemPage")
        assert failed["total"] == 1
        assert failed["items"][0]["status"] == "failed"
        page = checked(await http.get(f"/runs/{run_id}/items?limit=1&offset=1"), "ItemPage")
        assert page == {"total": 3, "items": all_items["items"][1:2]}
        empty = checked(await http.get(f"/runs/{run_id}/items?offset=99"), "ItemPage")
        assert empty == {"total": 3, "items": []}
        item_id = failed["items"][0]["item_id"]
        detail = checked(await http.get(f"/runs/{run_id}/items/{item_id}"), "ItemDetail")
        saved = json.loads((roots[2] / run_id / "items" / f"{item_id}.json").read_text())
        assert detail["failure"] == saved["failure"]
        assert detail["response"] == saved["response"]
        assert detail["status"] == "failed"


async def test_unscored_rows_fall_back_to_saved_files_and_metrics_404(roots):
    async with session(roots) as (app, http, _):
        run_id = await start(http)
        await terminal(app.state.manager, run_id)
        for name in ("metrics.json", "item_rows.json"):
            (roots[2] / run_id / name).unlink()
        app.state.manager.score_states.pop(run_id, None)
        rows = checked(await http.get(f"/runs/{run_id}/items"), "ItemPage")
        assert rows["total"] == 2
        assert all(row["gold"] is None and row["pred"] is None and row["match"] is None
                   for row in rows["items"])
        error = checked(await http.get(f"/runs/{run_id}/metrics"), "ErrorResponse", 404)
        assert error["error"]["code"] == "not_found"
        assert checked(await http.get(f"/runs/{run_id}"), "RunDetail")["score_state"] == "pending"


async def test_item_gold_is_opaque_computed_on_demand_and_never_written(roots, monkeypatch):
    async with session(roots) as (app, http, _):
        run_id = await start(http)
        await terminal(app.state.manager, run_id)
        item_id = store.load_run(roots[2], run_id)["item_ids"][0]
        before = {p.relative_to(roots[2]): p.read_bytes() for p in roots[2].rglob("*") if p.is_file()}
        calls = []
        main_thread = threading.get_ident()
        opaque_gold = {"sentences": [{"text": "fictional", "label": "supported"}]}
        dataset = await app.state.manager.get_dataset("synthetic")

        def gold(item):
            calls.append((item.id, threading.get_ident()))
            return opaque_gold

        monkeypatch.setattr(dataset.adapter, "gold", gold)
        for _ in range(2):
            body = checked(await http.get(f"/runs/{run_id}/items/{item_id}"), "ItemDetail")
            assert body["gold"] == opaque_gold
        assert len(calls) == 2
        assert all(item == item_id and thread_id != main_thread for item, thread_id in calls)
        after = {p.relative_to(roots[2]): p.read_bytes() for p in roots[2].rglob("*") if p.is_file()}
        assert after == before


async def test_item_id_must_belong_to_run_even_when_extra_file_exists(roots):
    async with session(roots) as (app, http, _):
        run_id = await start(http)
        await terminal(app.state.manager, run_id)
        first = next((roots[2] / run_id / "items").glob("*.json"))
        (first.parent / "not-selected.json").write_bytes(first.read_bytes())
        response = await http.get(f"/runs/{run_id}/items/not-selected")
        assert checked(response, "ErrorResponse", 404)["error"]["code"] == "not_found"


@pytest.mark.parametrize("query", ["filter=weird", "limit=0", "offset=-1", "limit=abc"])
async def test_invalid_item_query_has_safe_schema_valid_error(roots, query):
    async with session(roots) as (app, http, _):
        run_id = await start(http)
        await terminal(app.state.manager, run_id)
        response = await http.get(f"/runs/{run_id}/items?{query}")
        assert checked(response, "ErrorResponse", 422)["error"]["code"] == "invalid_request"


async def test_compare_uses_current_items_and_validates_nested_bundle(roots):
    class VaryingBackend(FakeBackend):
        clean = False

        def build_response(self, request, mode="ok"):
            body = super().build_response(request, mode)
            if self.clean:
                for claim in body["claims"]:
                    claim["verdict"] = "out_of_scope"
                    claim["out_of_scope_reason"] = "Offline neutral prediction fixture."
            return body

    backend = VaryingBackend()
    async with session(roots, backend) as (app, http, _):
        run_a = await start(http)
        await terminal(app.state.manager, run_a)
        backend.clean = True
        run_b = await start(http)
        await terminal(app.state.manager, run_b)
        before = {p.relative_to(roots[2]): p.read_bytes() for p in roots[2].rglob("*") if p.is_file()}
        comparison = checked(await http.get("/compare", params={"a": run_a, "b": run_b}), "Comparison")
        assert comparison["n_shared"] == 2
        assert len(comparison["disagreements"]) == 2
        assert comparison["deltas"]
        after = {p.relative_to(roots[2]): p.read_bytes() for p in roots[2].rglob("*") if p.is_file()}
        assert after == before


async def test_compare_refuses_different_datasets(roots):
    datasets, _, _ = roots
    shutil.copytree(datasets / "eaudit/synthetic", datasets / "eaudit/other")
    path = datasets / "eaudit/other" / "metadata.json"
    metadata = json.loads(path.read_text())
    metadata["name"] = "other"
    path.write_text(json.dumps(metadata))
    async with session(roots) as (app, http, _):
        run_a = await start(http)
        await terminal(app.state.manager, run_a)
        run_b = checked(await http.post("/runs", json={
            "dataset": "other", "split": "dev", "n": 2,
        }), "RunCreated", 202)["run_id"]
        await terminal(app.state.manager, run_b)
        response = await http.get("/compare", params={"a": run_a, "b": run_b})
        assert checked(response, "ErrorResponse", 422)["error"]["code"] == "invalid_request"


async def test_rescore_hides_old_reports_and_rows_until_done(roots, monkeypatch):
    async with session(roots) as (app, http, _):
        run_id = await start(http)
        await terminal(app.state.manager, run_id)
        original = scoring.score
        entered, release = threading.Event(), threading.Event()

        def blocked_score(*args, **kwargs):
            entered.set()
            assert release.wait(3)
            return original(*args, **kwargs)

        monkeypatch.setattr(scoring, "score", blocked_score)
        try:
            checked(await http.post(f"/runs/{run_id}/rescore"), "RunSummary", 202)
            async with asyncio.timeout(2):
                while not entered.is_set():
                    await asyncio.sleep(0.001)
            checked(await http.get(f"/runs/{run_id}/metrics"), "ErrorResponse", 404)
            page = checked(await http.get(f"/runs/{run_id}/items"), "ItemPage")
            assert all(row["gold"] is None and row["match"] is None for row in page["items"])
        finally:
            release.set()
        await terminal(app.state.manager, run_id)
        checked(await http.get(f"/runs/{run_id}/metrics"), "MetricsReport")


async def test_resume_hides_old_reports_even_after_restart(roots):
    async with session(roots) as (app, http, _):
        run_id = await start(http, max_cost_usd=0.005)
        await terminal(app.state.manager, run_id)
    # A stopped resume leaves old scoring artifacts on disk; they describe older items.
    store.update_run(roots[2], run_id, state="running", finished_at=None)
    async with session(roots) as (_, http, _):
        detail = checked(await http.get(f"/runs/{run_id}"), "RunDetail")
        assert detail["state"] == "interrupted"
        assert detail["score_state"] == "pending"
        checked(await http.get(f"/runs/{run_id}/metrics"), "ErrorResponse", 404)
        page = checked(await http.get(f"/runs/{run_id}/items"), "ItemPage")
        assert all(row["gold"] is None for row in page["items"])


@pytest.mark.parametrize("relative,endpoint", [
    ("run.json", ""), ("run.lock", ""), ("metrics.json", "/metrics"),
    ("item_rows.json", "/items"), ("items", "/items"), ("item", "/item"),
])
async def test_read_paths_reject_symlinks_outside_run_root(roots, tmp_path, relative, endpoint):
    async with session(roots) as (app, http, _):
        run_id = await start(http)
        await terminal(app.state.manager, run_id)
        item_id = store.load_run(roots[2], run_id)["item_ids"][0]
        source = roots[2] / run_id / relative
        if relative == "item":
            source = roots[2] / run_id / "items" / f"{item_id}.json"
            endpoint = f"/items/{item_id}"
        outside = tmp_path / "outside"
        source.replace(outside)
        source.symlink_to(outside, target_is_directory=outside.is_dir())
        response = await http.get(f"/runs/{run_id}{endpoint}")
        assert checked(response, "ErrorResponse", 404)["error"]["code"] == "not_found"


@pytest.mark.parametrize("suffix", ["", "/metrics", "/items", "/items/missing"])
async def test_unknown_run_read_is_safe_404(roots, suffix):
    async with session(roots) as (_, http, _):
        response = await http.get("/runs/20260101T000000Z-synthetic-ab12cd" + suffix)
        assert checked(response, "ErrorResponse", 404)["error"]["code"] == "not_found"


async def test_failed_rescore_keeps_old_files_hidden(roots, monkeypatch):
    async with session(roots) as (app, http, _):
        run_id = await start(http)
        await terminal(app.state.manager, run_id)
        report_path = roots[2] / run_id / "metrics.json"
        old_report = report_path.read_bytes()

        def failed_score(*args, **kwargs):
            raise RuntimeError("SECRET-RESCORE-FAILURE")

        monkeypatch.setattr(scoring, "score", failed_score)
        checked(await http.post(f"/runs/{run_id}/rescore"), "RunSummary", 202)
        assert (await terminal(app.state.manager, run_id))["score_state"] == "failed"
        assert report_path.read_bytes() == old_report
        checked(await http.get(f"/runs/{run_id}/metrics"), "ErrorResponse", 404)
        page = checked(await http.get(f"/runs/{run_id}/items"), "ItemPage")
        assert all(row["gold"] is None and row["pred"] is None for row in page["items"])


async def test_detail_preserves_run_error_extra_fields(roots):
    async with session(roots) as (app, http, _):
        run_id = await start(http)
        await terminal(app.state.manager, run_id)
        path = roots[2] / run_id / "run.json"
        run = json.loads(path.read_text())
        run["error"] = {"kind": "fixture_failure", "message": "Exact fixture message",
                        "versions": {"expected": "0.0.1", "actual": "0.0.0"}}
        path.write_text(json.dumps(run))
        detail = checked(await http.get(f"/runs/{run_id}"), "RunDetail")
        assert detail["error"] == run["error"]
