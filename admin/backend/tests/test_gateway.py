import json
from pathlib import Path

import pytest
from conftest import PROJECT
from eaudit import contract
from eaudit.app import create_app as create_eaudit
from eaudit.config import Settings
from fastapi.testclient import TestClient
from onolys_admin_auth import ConfigError, IdTokenVerifier

from onolys_admin_backend import create_app, parse_cors_origins

pytestmark = pytest.mark.unit

CONTRACTS = Path(__file__).resolve().parents[3] / "docs" / "contracts"
ORIGIN = "https://admin.example"
EVIL = "https://evil.example"
ENV_ON = {
    "ENV": "prod",
    "ADMIN_AUTH": "on",
    "GCP_PROJECT": PROJECT,
    "ADMIN_ALLOWED_EMAILS": "alice@example.com",
    "ADMIN_CORS_ORIGINS": ORIGIN,
}
ENV_LOCAL = {"ENV": "local", "ADMIN_AUTH": "off", "ADMIN_CORS_ORIGINS": ORIGIN}


def eaudit_app(**kw):
    return create_eaudit(Settings(pipeline="stub", llm_mode="stub"), **kw)


@pytest.fixture
def example_request() -> dict:
    return json.loads((CONTRACTS / "examples" / "request.json").read_text())


@pytest.fixture
def secured(keys):
    verifier = IdTokenVerifier(PROJECT, fetch_certs=lambda: keys.certs)
    with TestClient(
        create_app(eaudit_app(), ENV_ON, verifier), raise_server_exceptions=False
    ) as c:
        yield c


@pytest.fixture
def local():
    with TestClient(create_app(eaudit_app(), ENV_LOCAL), raise_server_exceptions=False) as c:
        yield c


def auth(token):
    return {"Authorization": f"Bearer {token}"}


def post_audit(client, body, headers=None):
    return client.post(
        "/v1/audit",
        content=json.dumps(body).encode(),
        headers={"content-type": "application/json", **(headers or {})},
    )


# --- every route is gated ---
ROUTES = [
    ("POST", "/v1/audit"),
    ("GET", "/healthz"),
    ("GET", "/nope"),
    ("GET", "/docs"),
    ("GET", "/openapi.json"),
    ("DELETE", "/v1/audit"),
]


@pytest.mark.parametrize(("method", "path"), ROUTES)
def test_no_token_401(secured, method, path):
    r = secured.request(method, path)
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "unauthenticated"


@pytest.mark.parametrize(("method", "path"), ROUTES)
def test_garbage_token_401(secured, method, path):
    assert secured.request(method, path, headers=auth("garbage")).status_code == 401


@pytest.mark.parametrize(("method", "path"), ROUTES)
def test_not_allowlisted_403(secured, keys, method, path):
    tok = keys.mint(email="mallory@example.com")
    assert secured.request(method, path, headers=auth(tok)).status_code == 403


def test_unverified_email_403(secured, keys):
    tok = keys.mint(email_verified=False)
    assert secured.get("/healthz", headers=auth(tok)).status_code == 403


def test_valid_token_succeeds(secured, keys, example_request):
    h = auth(keys.mint())
    assert secured.get("/healthz", headers=h).json() == {"status": "ok"}
    r = post_audit(secured, example_request, h)
    assert r.status_code == 200
    assert contract.validate_response(r.json()) == []
    assert secured.get("/nope", headers=h).status_code == 404  # reaches eaudit


def test_allowlist_case_insensitive(secured, keys):
    assert secured.get("/healthz", headers=auth(keys.mint(email="Alice@Example.com"))).status_code == 200


# --- CORS ---
PREFLIGHT = {
    "Access-Control-Request-Method": "POST",
    "Access-Control-Request-Headers": "authorization,content-type",
}


def test_preflight_allowed_origin_without_token(secured):
    r = secured.options("/v1/audit", headers={"Origin": ORIGIN, **PREFLIGHT})
    assert r.status_code == 200
    assert r.headers["access-control-allow-origin"] == ORIGIN
    allowed = {h.strip().lower() for h in r.headers["access-control-allow-headers"].split(",")}
    assert {"authorization", "content-type"} <= allowed
    assert "x-evil" not in allowed
    assert "access-control-allow-credentials" not in r.headers


def test_preflight_disallowed_origin_rejected(secured):
    r = secured.options("/v1/audit", headers={"Origin": EVIL, **PREFLIGHT})
    assert r.status_code == 400
    assert "access-control-allow-origin" not in r.headers


def test_preflight_disallowed_header_rejected(secured):
    h = {"Origin": ORIGIN, **PREFLIGHT, "Access-Control-Request-Headers": "x-evil"}
    assert secured.options("/v1/audit", headers=h).status_code == 400


def test_cors_headers_on_401_for_allowed_origin_only(secured):
    ok = secured.get("/healthz", headers={"Origin": ORIGIN})
    assert ok.status_code == 401 and ok.headers["access-control-allow-origin"] == ORIGIN
    bad = secured.get("/healthz", headers={"Origin": EVIL})
    assert bad.status_code == 401 and "access-control-allow-origin" not in bad.headers


def test_cors_headers_on_success(secured, keys):
    r = secured.get("/healthz", headers={**auth(keys.mint()), "Origin": ORIGIN})
    assert r.status_code == 200 and r.headers["access-control-allow-origin"] == ORIGIN


# --- non-preflight OPTIONS passes auth by design; it must not reach handlers or leak ---
class SpyPipeline:
    calls = 0

    async def run(self, *a, **k):  # pragma: no cover - must never run
        SpyPipeline.calls += 1
        raise AssertionError("handler reached")


@pytest.mark.parametrize("headers", [{}, {"Origin": ORIGIN}, {"Access-Control-Request-Method": "POST"}])
@pytest.mark.parametrize("path", ["/v1/audit", "/healthz", "/nope"])
def test_plain_options_no_handler_no_data(keys, path, headers):
    SpyPipeline.calls = 0
    app = create_app(
        eaudit_app(pipeline=SpyPipeline()),
        ENV_ON,
        IdTokenVerifier(PROJECT, fetch_certs=lambda: keys.certs),
    )
    with TestClient(app, raise_server_exceptions=False) as c:
        r = c.options(path, headers=headers)
    assert SpyPipeline.calls == 0
    assert r.status_code in (400, 404, 405)
    assert r.status_code != 200 or r.content == b""
    assert b"claims" not in r.content and b'"ok"' not in r.content


# --- eaudit contract unchanged through the gateway (auth off, ENV=local) ---
def test_local_healthz(local):
    assert local.get("/healthz").json() == {"status": "ok"}


def test_local_audit_contract_ok(local, example_request):
    r = post_audit(local, example_request)
    assert r.status_code == 200
    body = r.json()
    assert contract.validate_response(body) == []
    assert body["request_id"] == example_request["request_id"]


@pytest.mark.parametrize(
    ("body", "headers", "status", "code"),
    [
        (b"{nope", {}, 400, "invalid_json"),
        (b"[1,2]", {}, 400, "invalid_json"),
        (b"{}", {"content-type": "text/plain"}, 415, "unsupported_media_type"),
    ],
)
def test_local_audit_contract_errors(local, body, headers, status, code):
    h = {"content-type": "application/json", **headers}
    r = local.post("/v1/audit", content=body, headers=h)
    assert r.status_code == status
    err = r.json()
    assert contract.validate_error(err) == []
    assert err["details"][0]["code"] == code


def test_local_unknown_path_404(local):
    assert local.get("/nope").status_code == 404


# --- config ---
def test_cors_origin_parsing():
    assert parse_cors_origins(" https://a.example, https://b.example ,") == [
        "https://a.example",
        "https://b.example",
    ]
    assert parse_cors_origins("") == []
    for bad in ("*", "https://*.example.com", "null"):
        with pytest.raises(ConfigError):
            parse_cors_origins(bad)


def test_startup_fails_without_allowlist():
    env = {k: v for k, v in ENV_ON.items() if k != "ADMIN_ALLOWED_EMAILS"}
    with pytest.raises(ConfigError):
        create_app(eaudit_app(), env)


def test_unset_env_does_not_disable_auth():
    with pytest.raises(ConfigError):
        create_app(eaudit_app(), {})
    with pytest.raises(ConfigError):
        create_app(eaudit_app(), {"ADMIN_AUTH": "off"})
