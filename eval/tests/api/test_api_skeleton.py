import logging

import httpx
import pytest
from fastapi import APIRouter

from iaudit_eval.server.app import create_app
from iaudit_eval.server.guards import (
    ApiError,
    Settings,
    validate_bind,
    validate_dataset_id,
    validate_item_id,
    validate_run_id,
)

SENTINEL = "ZZ-SENTINEL-PHI-ZZ"
RUN_ID = "20260101T000000Z-synthetic-ab12cd"


def make_app(tmp_path, **kw):
    app = create_app(Settings(**kw), runs_root=tmp_path / "runs", datasets_root=tmp_path / "ds")
    r = APIRouter()

    @r.get("/ping")
    async def ping():
        return {"ok": True}

    @r.get("/guard-datasets/{name}")
    async def ds(name: str):
        validate_dataset_id(name)
        return {"name": name}

    @r.get("/guard-runs/{run_id}/items/{item_id}")
    async def item(run_id: str, item_id: str):
        validate_run_id(run_id)
        validate_item_id(item_id, {"a.1"})
        return {}

    @r.get("/boom")
    async def boom():
        raise RuntimeError(f"secret {SENTINEL}")

    @r.post("/body")
    async def body(payload: dict):
        return payload

    @r.get("/num/{n}")
    async def num(n: int):
        return n

    app.include_router(r)
    return app


def client(app, **kw):
    kw.setdefault("base_url", "http://localhost:8100")
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app, raise_app_exceptions=False), **kw)


def assert_error(resp, status, code):
    assert resp.status_code == status
    body = resp.json()
    assert set(body) == {"error"}
    assert body["error"]["code"] == code
    assert isinstance(body["error"]["message"], str)
    assert set(body["error"]) <= {"code", "message", "detail"}


async def test_ok_and_allowed_origin(tmp_path):
    async with client(make_app(tmp_path)) as c:
        assert (await c.get("/ping")).status_code == 200
        r = await c.get("/ping", headers={"Origin": "http://localhost:5173"})
        assert r.status_code == 200
        r = await c.get("/ping", headers={"Origin": "http://127.0.0.1:5173"})
        assert r.status_code == 200
        assert "access-control-allow-origin" not in r.headers


@pytest.mark.parametrize("origin", ["http://evil.example", "null", "http://localhost:5174"])
async def test_foreign_origin_403(tmp_path, origin):
    async with client(make_app(tmp_path)) as c:
        assert_error(await c.post("/body", json={}, headers={"Origin": origin}), 403, "forbidden")


async def test_origin_env_override(tmp_path):
    app = make_app(tmp_path, allowed_origins=frozenset({"http://localhost:3000"}))
    async with client(app) as c:
        assert (await c.get("/ping", headers={"Origin": "http://localhost:3000"})).status_code == 200
        r = await c.get("/ping", headers={"Origin": "http://localhost:5173"})
        assert_error(r, 403, "forbidden")


@pytest.mark.parametrize("host", ["evil.example", "localhost.evil.example", "localhost:abc", "[::1]"])
async def test_foreign_host_403(tmp_path, host):
    async with client(make_app(tmp_path)) as c:
        assert_error(await c.get("/ping", headers={"Host": host}), 403, "forbidden")


@pytest.mark.parametrize("host", ["localhost", "127.0.0.1", "localhost:8100", "127.0.0.1:9999"])
async def test_local_host_ok(tmp_path, host):
    async with client(make_app(tmp_path)) as c:
        assert (await c.get("/ping", headers={"Host": host})).status_code == 200


async def test_no_cors_headers_on_preflight(tmp_path):
    async with client(make_app(tmp_path)) as c:
        r = await c.options(
            "/ping",
            headers={"Origin": "http://localhost:5173", "Access-Control-Request-Method": "GET"},
        )
        assert "access-control-allow-origin" not in r.headers
        assert_error(r, 405, "invalid_request")


@pytest.mark.parametrize(
    "path",
    ["/guard-datasets/..", "/guard-datasets/Up", "/guard-datasets/-x", "/guard-datasets/%2e%2e", "/guard-datasets/a%2F..%2Fb",
     "/guard-datasets/" + "a" * 65],
)
async def test_bad_dataset_ids_404(tmp_path, path):
    async with client(make_app(tmp_path)) as c:
        assert_error(await c.get(path), 404, "not_found")


async def test_good_dataset_id(tmp_path):
    async with client(make_app(tmp_path)) as c:
        assert (await c.get("/guard-datasets/tofueval_x-1")).json() == {"name": "tofueval_x-1"}


@pytest.mark.parametrize(
    "run_id", ["..", "x", "20260101T000000Z-Syn-ab12cd", "20260101T000000Z-syn-ABCDEF",
               "%2e%2e%2f%2e%2e", "20260101T000000Z-syn-ab12cd/.."]
)
async def test_bad_run_ids_404(tmp_path, run_id):
    async with client(make_app(tmp_path)) as c:
        assert_error(await c.get(f"/guard-runs/{run_id}/items/a.1"), 404, "not_found")


async def test_item_allowlist(tmp_path):
    async with client(make_app(tmp_path)) as c:
        assert (await c.get(f"/guard-runs/{RUN_ID}/items/a.1")).status_code == 200
        for bad in ["b", "..", "a.1%2F..", "%2e%2e"]:
            assert_error(await c.get(f"/guard-runs/{RUN_ID}/items/{bad}"), 404, "not_found")


def test_validators_direct(tmp_path):
    assert validate_run_id(RUN_ID) == RUN_ID
    with pytest.raises(ApiError):
        validate_run_id("../x")
    with pytest.raises(ApiError):
        validate_item_id("../etc", {"../etc"})  # allowlisted but unsafe
    with pytest.raises(ApiError):
        validate_item_id("ok", set())


def test_path_under_root(tmp_path):
    from iaudit_eval.server.guards import resolve_under

    root = tmp_path / "runs"
    root.mkdir()
    assert resolve_under(root, RUN_ID, "items") == (root / RUN_ID / "items").resolve()
    for bad in ("..", "../x", "/etc"):
        with pytest.raises(ApiError):
            resolve_under(root, bad)
    (tmp_path / "out").mkdir()
    (root / "link").symlink_to(tmp_path / "out")
    with pytest.raises(ApiError):
        resolve_under(root, "link", "f")


async def test_500_fixed_message(tmp_path, caplog):
    async with client(make_app(tmp_path)) as c:
        with caplog.at_level(logging.DEBUG):
            r = await c.get("/boom")
    assert_error(r, 500, "internal_error")
    assert SENTINEL not in r.text
    assert SENTINEL not in caplog.text
    assert "RuntimeError" in caplog.text


async def test_error_shapes(tmp_path):
    async with client(make_app(tmp_path)) as c:
        assert_error(await c.get("/nope"), 404, "not_found")
        assert_error(await c.post("/ping"), 405, "invalid_request")
        r = await c.get("/num/" + SENTINEL)
        assert_error(r, 422, "invalid_request")
        assert SENTINEL not in r.text
        r = await c.post("/body", content=f'["{SENTINEL}"')
        assert_error(r, 422, "invalid_request")
        assert SENTINEL not in r.text


async def test_logging_safe(tmp_path, caplog):
    async with client(make_app(tmp_path)) as c:
        with caplog.at_level(logging.DEBUG):
            await c.get(f"/guard-runs/{RUN_ID}/items/a.1?x={SENTINEL}")
            await c.post("/body", json={"t": SENTINEL})
            await c.get("/guard-datasets/" + SENTINEL.lower())
    # httpx's own client logger echoes the URL; only the server's loggers matter here.
    text = "\n".join(r.getMessage() for r in caplog.records if not r.name.startswith("httpx"))
    assert SENTINEL not in text and SENTINEL.lower() not in text
    assert "a.1" not in text and RUN_ID not in text
    assert "/guard-runs/{run_id}/items/{item_id}" in text
    assert "method=" in text and "status=" in text and "duration_ms=" in text


def test_validate_bind():
    validate_bind("127.0.0.1", allow_remote=False)
    for h in ("0.0.0.0", "localhost", "192.168.1.5"):
        with pytest.raises(ValueError):
            validate_bind(h, allow_remote=False)
    validate_bind("0.0.0.0", allow_remote=True)


def test_settings_from_env():
    s = Settings.from_env({})
    assert (s.host, s.port, s.backend_url) == ("127.0.0.1", 8100, "http://127.0.0.1:8000")
    assert s.allow_remote is False
    s = Settings.from_env(
        {"IAUDIT_EVAL_PORT": "9", "IAUDIT_BACKEND_URL": "http://b", "IAUDIT_EVAL_ALLOW_REMOTE": "1",
         "IAUDIT_EVAL_ALLOWED_ORIGINS": "http://a, http://c"}
    )
    assert s.port == 9 and s.backend_url == "http://b" and s.allow_remote
    assert s.allowed_origins == frozenset({"http://a", "http://c"})


def test_main_refuses_remote_host(monkeypatch):
    from iaudit_eval.server import app as appmod

    monkeypatch.delenv("IAUDIT_EVAL_ALLOW_REMOTE", raising=False)
    with pytest.raises(ValueError):
        appmod.main(["--host", "0.0.0.0"])


def test_main_runs_uvicorn_access_log_off(monkeypatch):
    from iaudit_eval.server import app as appmod

    calls = {}
    monkeypatch.setattr(appmod.uvicorn, "run", lambda *a, **k: calls.update(a=a, k=k))
    appmod.main([])
    assert calls["k"]["host"] == "127.0.0.1" and calls["k"]["port"] == 8100
    assert calls["k"]["access_log"] is False


def test_module_level_app():
    from iaudit_eval.server.app import app

    assert app.title


async def test_lifespan_owns_default_backend_client(tmp_path):
    app = create_app(Settings(), runs_root=tmp_path / "r", datasets_root=tmp_path / "d")
    async with app.router.lifespan_context(app):
        assert app.state.backend_client.base_url == "http://127.0.0.1:8000"
    injected = object()
    app2 = create_app(Settings(), backend_client=injected, runs_root=tmp_path, datasets_root=tmp_path)
    async with app2.router.lifespan_context(app2):
        assert app2.state.backend_client is injected


@pytest.mark.parametrize("peer", ["127.0.0.1", "127.5.4.3", "::1"])
async def test_loopback_peer_allowed(tmp_path, peer):
    app = make_app(tmp_path)
    transport = httpx.ASGITransport(app=app, client=(peer, 5000))
    async with httpx.AsyncClient(transport=transport, base_url="http://localhost:8100") as c:
        assert (await c.get("/ping")).status_code == 200


@pytest.mark.parametrize("peer", ["203.0.113.5", "10.0.0.2", "testclient", "::ffff:8.8.8.8"])
async def test_non_loopback_peer_403_even_with_valid_host(tmp_path, peer):
    app = make_app(tmp_path)
    transport = httpx.ASGITransport(app=app, client=(peer, 5000))
    async with httpx.AsyncClient(transport=transport, base_url="http://localhost:8100") as c:
        assert_error(await c.get("/ping"), 403, "forbidden")


async def test_non_loopback_peer_allowed_with_allow_remote(tmp_path):
    app = make_app(tmp_path, allow_remote=True)
    transport = httpx.ASGITransport(app=app, client=("203.0.113.5", 5000))
    async with httpx.AsyncClient(transport=transport, base_url="http://localhost:8100") as c:
        assert (await c.get("/ping")).status_code == 200
