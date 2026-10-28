import pytest
from fastapi import FastAPI, Query
from fastapi.testclient import TestClient

from eaudit import contract
from eaudit.api.errors import ApiError, register_error_handlers
from eaudit.llm.errors import LLMUnavailable


def make_app() -> FastAPI:
    app = FastAPI()
    register_error_handlers(app)

    @app.get("/api-error")
    def api_error():
        raise ApiError("invalid_request", "bad thing", 400, request_id="r-1")

    @app.get("/unavailable")
    def unavailable():
        raise LLMUnavailable("provider said SENTINEL")

    @app.get("/timeout")
    def timeout():
        raise TimeoutError("SENTINEL")

    @app.get("/boom")
    def boom():
        raise RuntimeError("SENTINEL secret transcript text")

    @app.get("/q")
    def q(n: int = Query(...)):
        return n

    @app.post("/only-post")
    def only_post():
        return {}

    return app


@pytest.fixture
def client():
    return TestClient(make_app(), raise_server_exceptions=False)


CASES = [
    ("/api-error", 400, "invalid_request"),
    ("/unavailable", 503, "unavailable"),
    ("/timeout", 504, "unavailable"),
    ("/boom", 500, "internal_error"),
    ("/nope", 404, "other"),
    ("/q", 422, "invalid_request"),
    ("/q?n=SENTINEL", 422, "invalid_request"),
]


@pytest.mark.parametrize(("path", "status", "code"), CASES)
def test_error_rows(client, path, status, code):
    r = client.get(path)
    assert r.status_code == status
    body = r.json()
    assert body["error"]["code"] == code
    assert contract.validate_error(body) == []
    assert "SENTINEL" not in r.text


def test_405(client):
    r = client.get("/only-post")
    assert r.status_code == 405
    assert r.json()["error"]["code"] == "other"
    assert contract.validate_error(r.json()) == []


def test_request_id_echoed(client):
    assert client.get("/api-error").json()["request_id"] == "r-1"
    assert "request_id" not in client.get("/boom").json()


def test_500_message_generic(client):
    assert client.get("/boom").json()["error"]["message"] == "Internal server error."
