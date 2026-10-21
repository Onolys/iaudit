"""Route-wide contract, containment, cross-site and PHI checks using only fakes."""

import builtins
import hashlib
import io
import json
import logging
import os
import shutil
import socket
from dataclasses import replace
from pathlib import Path

import httpx
import pytest
from fakes.fake_backend import FakeBackend
from test_dataset_routes import checked, session
from test_run_control import start, terminal

from iaudit_eval import paths, store

TEXT = "PRIVATEtranscriptAndAssessmentSentinel"
ITEM = "PRIVATEitemIdentifierSentinel"
UNKNOWN_RUN = "20260101T000000Z-synthetic-ab12cd"
ROUTES = (
    "GET /health", "GET /datasets", "GET /datasets/{name}",
    "POST /datasets/{name}/download", "GET /datasets/{name}/download",
    "POST /runs/estimate", "POST /runs", "GET /runs", "GET /runs/{id}",
    "POST /runs/{id}/abort", "POST /runs/{id}/resume", "GET /runs/{id}/metrics",
    "GET /runs/{id}/items", "GET /runs/{id}/items/{item_id}",
    "POST /runs/{id}/rescore", "GET /compare",
)
ERRORS = (
    ("invalid_request", 422), ("not_found", 404), ("run_active", 409),
    ("bad_state", 409), ("data_missing", 409), ("backend_unreachable", 502),
    ("schema_mismatch", 409), ("forbidden", 403), ("internal_error", 500),
)


@pytest.fixture(autouse=True)
def block_network(monkeypatch):
    def blocked(*args, **kwargs):
        pytest.fail("cross-cutting API test attempted network access")

    monkeypatch.setattr(socket.socket, "connect", blocked)
    monkeypatch.setattr(socket.socket, "connect_ex", blocked)
    monkeypatch.setattr(socket, "getaddrinfo", blocked)


@pytest.fixture
def roots(tmp_path):
    datasets = tmp_path / "datasets"
    shutil.copytree(paths.datasets_dir() / "synthetic", datasets / "synthetic")
    adapter = datasets / "synthetic/adapter.py"
    source = adapter.read_text().replace("garden-clean", ITEM)
    source = source.replace("Let us settle the plot rota", TEXT + " Let us settle the plot rota")
    source = source.replace("Mira offered to water", TEXT + " Mira offered to water")
    adapter.write_text(source)
    return datasets, tmp_path / "data", tmp_path / "runs"


def schema():
    return json.loads((paths.repo_root() / "eval/api/eval-api.schema.json").read_text())


def snapshot(roots):
    return {
        (str(root), str(path.relative_to(root))): hashlib.sha256(path.read_bytes()).hexdigest()
        for root in roots for path in root.rglob("*") if path.is_file() and not path.is_symlink()
    }


def assert_safe_logs(caplog):
    assert TEXT not in caplog.text
    # B2 intentionally logs its filename-safe item_id; B4 must log only route templates.
    http_messages = [record.getMessage() for record in caplog.records
                     if record.name == "iaudit_eval" and record.getMessage().startswith("http_request ")]
    assert http_messages
    assert all(ITEM not in message and TEXT not in message for message in http_messages)


async def seed(app, http):
    a = await start(http, split="all", n=8)
    await terminal(app.state.manager, a)
    b = await start(http, split="all", n=1)
    await terminal(app.state.manager, b)
    return a, b


def endpoint(route, run_id=UNKNOWN_RUN, item_id=ITEM, name="synthetic"):
    method, template = route.split(" ", 1)
    return method, template.format(id=run_id, item_id=item_id, name=name)


def test_every_application_route_and_error_enum_has_a_cross_cutting_case(roots):
    from iaudit_eval.server.app import create_app

    app = create_app(datasets_root=roots[0], data_root=roots[1], runs_root=roots[2])
    actual = {f"{method.upper()} {path}" for path, methods in app.openapi()["paths"].items()
              for method in methods}
    assert actual == set(ROUTES) == set(schema()["x-routes"])
    assert {code for code, _ in ERRORS} == set(schema()["$defs"]["Error"]["properties"]["code"]["enum"])


@pytest.mark.parametrize("route", ROUTES)
async def test_every_real_route_returns_committed_schema_and_safe_logs(roots, route, caplog):
    caplog.set_level(logging.INFO, logger="iaudit_eval")
    async with session(roots) as (app, http, backend):
        a, b = await seed(app, http)
        method, url = endpoint(route, a)
        if route == "POST /runs/{id}/abort":
            backend.delay = 0.03
            active = await start(http, split="all", n=8)
            method, url = endpoint(route, active)
        elif route == "POST /runs/{id}/resume":
            store.update_run(roots[2], a, state="aborted")
        payload = None
        if route in {"POST /runs", "POST /runs/estimate"}:
            payload = {"dataset": "synthetic", "split": "all", "n": 1}
        if route == "POST /runs":
            payload["tags"] = {"note": TEXT}
        response = await http.request(method, url, params={"a": a, "b": b, "trace": TEXT},
                                      json=payload)
        status = 202 if route in {"POST /runs", "POST /runs/{id}/rescore",
                                  "POST /datasets/{name}/download"} else 200
        checked(response, schema()["x-routes"][route], status)
        # Inspect the actual transcript/assessment fixture, so a missing sentinel
        # cannot make the log test vacuously pass.
        detail = checked(await http.get(f"/runs/{a}/items/{ITEM}"), "ItemDetail")
        assert TEXT in json.dumps(detail["request"]["transcript"])
        assert TEXT in json.dumps(detail["request"]["assessment"])
    assert_safe_logs(caplog)


@pytest.mark.parametrize("route", ROUTES)
@pytest.mark.parametrize("headers", [
    {"Origin": "https://foreign.invalid"}, {"Host": "foreign.invalid"},
])
async def test_every_route_rejects_foreign_origin_host_without_work(roots, route, headers, caplog):
    caplog.set_level(logging.INFO, logger="iaudit_eval")
    async with session(roots) as (_, http, backend):
        before = snapshot(roots)
        method, url = endpoint(route)
        response = await http.request(method, url, params={"a": UNKNOWN_RUN, "b": UNKNOWN_RUN,
                                                          "trace": TEXT}, headers=headers,
                                      json={"dataset": "synthetic", "split": "all",
                                            "tags": {"note": TEXT}})
        assert checked(response, "ErrorResponse", 403)["error"]["code"] == "forbidden"
        assert TEXT not in response.text and ITEM not in response.text
        assert snapshot(roots) == before
        assert backend.count == backend.audit_work == 0
    assert_safe_logs(caplog)


@pytest.mark.parametrize("value", ["../outside", "%2e%2e%2foutside", "..%5coutside",
                                    "%252e%252e%252foutside", "%2foutside"])
async def test_traversal_variants_cannot_touch_files_or_spend(roots, tmp_path, value, monkeypatch, caplog):
    caplog.set_level(logging.INFO, logger="iaudit_eval")
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "metadata.json").write_text(TEXT)
    touched = []

    def guard_open(original):
        def guarded(file, *args, **kwargs):
            if isinstance(file, str | os.PathLike):
                target = Path(file).resolve()
                if target == outside or outside in target.parents:
                    touched.append(str(target))
                    raise AssertionError("attempted access outside injected roots")
            return original(file, *args, **kwargs)
        return guarded

    async with session(roots) as (app, http, backend):
        a, b = await seed(app, http)
        roots[0].joinpath("escape").symlink_to(outside, target_is_directory=True)
        roots[2].joinpath(UNKNOWN_RUN).symlink_to(outside, target_is_directory=True)
        requests = [(method, url) for route in ROUTES
                    if "{name}" in route or "{id}" in route
                    for method, url in [endpoint(route, value, ITEM, value)]]
        requests += [("GET", f"/runs/{a}/items/{value}"),
                     ("GET", "/datasets/escape"), ("GET", f"/runs/{UNKNOWN_RUN}")]
        before = snapshot(roots)
        count = backend.count
        with monkeypatch.context() as patch:
            for module, attr in ((builtins, "open"), (io, "open"), (os, "open")):
                patch.setattr(module, attr, guard_open(getattr(module, attr)))
            for method, url in requests:
                response = await http.request(method, url, params={"trace": TEXT})
                assert response.status_code in {404, 422}, (method, url, response.text)
                checked(response, "ErrorResponse", response.status_code)
                assert TEXT not in response.text and ITEM not in response.text
            for name in ("a", "b"):
                response = await http.get("/compare", params={"a": a, "b": b, name: value})
                checked(response, "ErrorResponse", 404)
        assert touched == []
        assert snapshot(roots) == before
        assert backend.count == count
    assert_safe_logs(caplog)


@pytest.mark.parametrize("code,status", ERRORS)
async def test_error_enum_is_exercised_over_http_without_sensitive_echo(
    roots, code, status, caplog, monkeypatch,
):
    caplog.set_level(logging.INFO, logger="iaudit_eval")

    class Backend(FakeBackend):
        unavailable = False

        async def handle(self, request):
            if self.unavailable:
                raise httpx.ConnectError(TEXT, request=request)
            return await super().handle(request)

    backend = Backend()
    async with session(roots, backend) as (app, http, _):
        a, _ = await seed(app, http)
        method, url, headers, payload = "POST", "/runs", {}, {"dataset": "synthetic", "split": "all", "n": 1}
        if code == "invalid_request":
            method, url = "GET", f"/runs/{a}/items?filter={TEXT}"
        elif code == "not_found":
            method, url = "GET", f"/runs/{a}/items/{TEXT}"
        elif code == "run_active":
            backend.delay = 0.04
            await start(http, split="all", n=8)
        elif code == "bad_state":
            url = f"/runs/{a}/resume"
        elif code == "data_missing":
            dataset = await app.state.manager.get_dataset("synthetic")
            dataset.meta = replace(dataset.meta, data_required=True)
        elif code == "backend_unreachable":
            backend.unavailable = True
        elif code == "schema_mismatch":
            backend.supported_version = "9.0.0"
        elif code == "forbidden":
            headers = {"Origin": "https://foreign.invalid"}
        elif code == "internal_error":
            def fail(*args):
                raise RuntimeError(TEXT)
            monkeypatch.setattr(app.state.reader, "detail", fail)
            method, url = "GET", f"/runs/{a}"
        response = await http.request(method, url, headers=headers, json=payload)
        assert checked(response, "ErrorResponse", status)["error"]["code"] == code
        assert TEXT not in response.text and ITEM not in response.text
    assert_safe_logs(caplog)


async def test_failed_download_status_never_echoes_exception_payload(roots, caplog, monkeypatch):
    caplog.set_level(logging.INFO, logger="iaudit_eval")
    async with session(roots) as (app, http, backend):
        dataset = await app.state.manager.get_dataset("synthetic")

        def failed_download(*args):
            raise ValueError(TEXT)

        monkeypatch.setattr(dataset.adapter, "download", failed_download, raising=False)
        checked(await http.post("/datasets/synthetic/download"), "DownloadStatus", 202)
        await app.state.manager.download_tasks["synthetic"]
        response = await http.get("/datasets/synthetic/download")
        assert checked(response, "DownloadStatus")["status"] == "failed"
        assert TEXT not in response.text
        assert response.json()["error"] == "Download failed."
        diagnostic = json.loads((roots[1] / "synthetic/download.json").read_text())
        assert TEXT in diagnostic["error"]  # private B2 diagnostic is preserved
        assert backend.count == backend.audit_work == 0
    assert_safe_logs(caplog)


async def test_restarted_server_redacts_persisted_download_failure(roots, caplog):
    caplog.set_level(logging.INFO, logger="iaudit_eval")
    document = roots[1] / "synthetic/download.json"
    document.parent.mkdir(parents=True)
    diagnostic = {"status": "failed", "error": f"ValueError: {TEXT}", "files": []}
    document.write_text(json.dumps(diagnostic))
    async with session(roots) as (_, http, backend):
        response = await http.get("/datasets/synthetic/download")
        assert checked(response, "DownloadStatus")["status"] == "failed"
        assert TEXT not in response.text
        assert response.json()["error"] == "Download failed."
        assert backend.count == backend.audit_work == 0
    assert json.loads(document.read_text()) == diagnostic
    assert_safe_logs(caplog)
