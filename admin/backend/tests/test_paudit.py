import asyncio
import json
import logging
from pathlib import Path

import jsonschema
import pytest
from conftest import PROJECT
from eaudit.app import create_app as create_eaudit
from eaudit.config import Settings
from fastapi.testclient import TestClient
from onolys_admin_auth import IdTokenVerifier
from paudit.result import schema_text
from paudit.stub import ExpectedStubClient

from onolys_admin_backend import create_app

ROOT = Path(__file__).resolve().parents[3]
FIX = ROOT / "protocols" / "miti-4.2.1" / "fixtures"
ORIGIN = "https://admin.example"
ENV_LOCAL = {"ENV": "local", "ADMIN_AUTH": "off", "ADMIN_CORS_ORIGINS": ORIGIN}
ENV_ON = {
    "ENV": "prod",
    "ADMIN_AUTH": "on",
    "GCP_PROJECT": PROJECT,
    "ADMIN_ALLOWED_EMAILS": "alice@example.com",
    "ADMIN_CORS_ORIGINS": ORIGIN,
}
NAMES = ["good_practice", "poor_practice", "short_session"]


def eaudit_app(**settings):
    return create_eaudit(Settings(pipeline="stub", llm_mode="stub", **settings))


def body_for(name="good_practice", **over):
    body = {
        "transcript": json.loads((FIX / f"{name}.json").read_text()),
        "pack": "miti@4.2.1",
        "params": json.loads((FIX / f"{name}.params.json").read_text()),
    }
    body.update(over)
    return body


def post(client, body, headers=None, raw=None):
    return client.post(
        "/v1/paudit",
        content=raw if raw is not None else json.dumps(body).encode(),
        headers={"content-type": "application/json", **(headers or {})},
    )


def make_client(env=ENV_LOCAL, name="good_practice", eaudit=None, llm="stub", verifier=None):
    llm = ExpectedStubClient(FIX / "expected.yaml", name) if llm == "stub" else llm
    app = create_app(eaudit or eaudit_app(), env, verifier, paudit_client=llm)
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture
def local():
    with make_client() as c:
        yield c


@pytest.mark.unit
def test_run_validates_against_result_schema(local):
    r = post(local, body_for(request_id="rid-1"))
    assert r.status_code == 200, r.text
    out = r.json()
    jsonschema.validate(out, json.loads(schema_text()))
    assert out["request_id"] == "rid-1"
    assert out["run_info"]["engine"] == "paudit"
    assert out["subject_speaker"] == "A"


@pytest.mark.unit
@pytest.mark.parametrize("missing", ["speaker_map", "change_goal"])
def test_missing_required_params_4xx(local, missing):
    body = body_for()
    del body["params"][missing]
    r = post(local, body)
    assert r.status_code == 400
    err = r.json()
    assert err["details"][0]["code"] == "missing_parameter"
    assert err["status"] == 400 and "message" in err and "schema_version" in err


@pytest.mark.unit
def test_missing_subject_4xx(local):
    body = body_for()
    body["params"]["speaker_map"] = {}
    assert post(local, body).status_code == 400


@pytest.mark.unit
@pytest.mark.parametrize(
    ("over", "code"),
    [
        ({"pack": "miti@9.9.9"}, "unknown_pack"),
        ({"transcript": {"nope": 1}}, "schema_violation"),
        ({"transcript": {"turns": []}}, "empty_transcript"),
        ({"params": {"speaker_map": {"subject": "A"}, "change_goal": "g", "n_runs": 99}}, "invalid_parameters"),
    ],
)
def test_bad_requests(local, over, code):
    r = post(local, body_for(**over))
    assert r.status_code == 400
    assert r.json()["details"][0]["code"] == code


@pytest.mark.unit
def test_invalid_json_and_media_type(local):
    r = post(local, None, raw=b"{nope")
    assert (r.status_code, r.json()["details"][0]["code"]) == (400, "invalid_json")
    r = local.post("/v1/paudit", content=b"{}", headers={"content-type": "text/plain"})
    assert (r.status_code, r.json()["details"][0]["code"]) == (415, "unsupported_media_type")


@pytest.mark.unit
def test_oversize_body_gives_size_error():
    with make_client(eaudit=eaudit_app(max_body_bytes=1000)) as c:
        r = post(c, body_for())
        assert r.status_code == 413
        assert r.json()["details"][0]["code"] == "body_too_large"
        # chunked (no content-length) bodies are capped too
        r = c.post(
            "/v1/paudit",
            content=iter([b"x" * 600, b"x" * 600]),
            headers={"content-type": "application/json"},
        )
        assert r.status_code == 413


class SlowClient:
    cancelled = False

    async def complete_json(self, req, metrics=None):
        try:
            await asyncio.sleep(30)
        except asyncio.CancelledError:
            SlowClient.cancelled = True
            raise


@pytest.mark.unit
def test_slow_run_504_at_deadline_and_server_stays_free():
    env = {**ENV_LOCAL, "ADMIN_PAUDIT_DEADLINE_S": "0.3"}
    with make_client(env, llm=SlowClient()) as c:
        r = post(c, body_for())
        assert r.status_code == 504
        err = r.json()
        assert err["details"][0]["code"] == "deadline_exceeded" and err["status"] == 504
        assert SlowClient.cancelled  # the run was cancelled, not left running
        assert c.get("/healthz").status_code == 200


@pytest.mark.unit
def test_fixtures_list_only_synthetic(local):
    r = local.get("/v1/paudit/fixtures")
    assert r.status_code == 200
    items = r.json()["fixtures"]
    assert sorted(i["name"] for i in items) == sorted(NAMES)
    for i in items:
        assert i["params"]["speaker_map"]["subject"] and i["params"]["change_goal"]
    one = local.get("/v1/paudit/fixtures/good_practice").json()
    assert one["transcript"]["synthetic"] is True
    # a served fixture runs as-is
    r = post(local, {"transcript": one["transcript"], "pack": one["pack"], "params": one["params"]})
    assert r.status_code == 200


@pytest.mark.unit
@pytest.mark.parametrize("name", ["..%2Fpack.yaml", "expected", "thresholds", "nope", "golden"])
def test_fixture_serves_nothing_else(local, name):
    r = local.get(f"/v1/paudit/fixtures/{name}")
    assert r.status_code in (404, 405)
    assert r.json()["details"][0]["code"] in ("not_found", "method_not_allowed")


@pytest.mark.unit
def test_non_synthetic_fixture_not_served(tmp_path, monkeypatch):
    import shutil

    proto = tmp_path / "protocols"
    shutil.copytree(ROOT / "protocols" / "miti-4.2.1", proto / "miti-4.2.1")
    f = proto / "miti-4.2.1" / "fixtures" / "good_practice.json"
    d = json.loads(f.read_text())
    d["synthetic"] = False
    f.write_text(json.dumps(d))
    monkeypatch.setenv("PAUDIT_PROTOCOLS_DIR", str(proto))
    with make_client() as c:
        names = [i["name"] for i in c.get("/v1/paudit/fixtures").json()["fixtures"]]
        assert "good_practice" not in names and "poor_practice" in names
        assert c.get("/v1/paudit/fixtures/good_practice").status_code == 404


@pytest.mark.unit
def test_logs_carry_no_transcript_text(local, caplog):
    caplog.set_level(logging.DEBUG)
    body = body_for()
    post(local, body)
    post(local, body_for(pack="x"))
    local.get("/v1/paudit/fixtures")
    texts = [t["text"] for t in body["transcript"]["turns"]]
    logged = "\n".join(r.getMessage() for r in caplog.records)
    assert "paudit_request" in logged
    for t in texts:
        assert t[:25] not in logged
    assert body["params"]["change_goal"] not in logged


# --- auth (task 2 tests cover the gateway; these cover the new routes) ---
PAUDIT_ROUTES = [
    ("POST", "/v1/paudit"),
    ("GET", "/v1/paudit/fixtures"),
    ("GET", "/v1/paudit/fixtures/good_practice"),
]


@pytest.fixture
def secured(keys):
    verifier = IdTokenVerifier(PROJECT, fetch_certs=lambda: keys.certs)
    with make_client(ENV_ON, verifier=verifier) as c:
        yield c


@pytest.mark.unit
@pytest.mark.parametrize(("method", "path"), PAUDIT_ROUTES)
def test_paudit_routes_need_token(secured, method, path):
    assert secured.request(method, path).status_code == 401
    assert secured.request(method, path, headers={"Authorization": "Bearer junk"}).status_code == 401


@pytest.mark.unit
@pytest.mark.parametrize(("method", "path"), PAUDIT_ROUTES)
def test_paudit_routes_allowlist_enforced(secured, keys, method, path):
    h = {"Authorization": f"Bearer {keys.mint(email='mallory@example.com')}"}
    assert secured.request(method, path, headers=h).status_code == 403


@pytest.mark.unit
def test_paudit_with_valid_token(secured, keys):
    h = {"Authorization": f"Bearer {keys.mint()}"}
    r = post(secured, body_for(), h)
    assert r.status_code == 200
    jsonschema.validate(r.json(), json.loads(schema_text()))
    assert secured.get("/v1/paudit/fixtures", headers=h).status_code == 200
    assert secured.get("/healthz", headers=h).status_code == 200  # eaudit still reached


@pytest.mark.live
def test_live_miti_synthetic_fixture(capsys):
    """Real model on the MITI synthetic fixture. Manual: `pytest -m live`. Never in CI."""
    import time

    with TestClient(create_app(eaudit_app(), ENV_LOCAL)) as c:
        t0 = time.monotonic()
        r = post(c, body_for())
        dt = time.monotonic() - t0
    assert r.status_code == 200, r.text[:300]
    jsonschema.validate(r.json(), json.loads(schema_text()))
    print(f"LIVE_OK duration_s={dt:.1f} calls={r.json()['run_info']['usage']['calls']}")
