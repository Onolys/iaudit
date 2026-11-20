import jsonschema
import pytest
from fastapi import HTTPException

from onolys_api.errors import ERROR_CODES, ApiError, error_body

pytestmark = pytest.mark.unit


def test_schema_enum_matches_codes_and_is_superset_of_eaudit(schema):
    import json
    from pathlib import Path

    enum = schema["properties"]["details"]["items"]["properties"]["code"]["enum"]
    assert list(enum) == list(ERROR_CODES)
    eaudit = json.loads(
        (
            Path(__file__).resolve().parents[2] / "docs/contracts/error-response.schema.json"
        ).read_text()
    )
    old = eaudit["properties"]["details"]["items"]["properties"]["code"]["enum"]
    assert set(old) <= set(enum)
    for new in (
        "unauthenticated",
        "forbidden",
        "invalid_state",
        "unsupported_audio",
        "audio_too_long",
        "audio_too_large",
        "audio_unreadable",
        "no_speech",
        "speakers_not_separated",
        "transcription_failed",
        "rating_invalid",
        "daily_cap_reached",
        "conflict",
    ):
        assert new in enum
    assert schema["properties"]["schema_version"] == {"const": "0.0.1"}


def test_error_body_validates(schema):
    body = error_body(429, "Daily cap.", [{"code": "daily_cap_reached", "message": "x"}], "r1")
    jsonschema.validate(body, schema)
    assert body["request_id"] == "r1"
    assert "request_id" not in error_body(400, "m", [{"code": "conflict", "message": "m"}])


async def test_not_found_validates_and_echoes_request_id(client, schema):
    r = await client.get("/v1/nope", headers={"X-Request-ID": "req-123"})
    assert r.status_code == 404
    jsonschema.validate(r.json(), schema)
    assert r.json()["request_id"] == "req-123" and r.json()["status"] == 404
    assert r.headers["x-request-id"] == "req-123"


async def test_generated_request_id_when_absent_or_unsafe(client, schema):
    r = await client.get("/v1/nope", headers={"X-Request-ID": "bad id\twith space"})
    jsonschema.validate(r.json(), schema)
    assert r.json()["request_id"] == r.headers["x-request-id"] != "bad id\twith space"


async def test_validation_error_is_422_without_values(client, schema, app):
    @app.get("/v1/_t/{n}")
    async def t(n: int):  # pragma: no cover
        return n

    r = await client.get("/v1/_t/SECRET-VALUE")
    assert r.status_code == 422
    jsonschema.validate(r.json(), schema)
    assert "SECRET-VALUE" not in r.text


async def test_api_error_http_exception_and_unhandled(client, schema, app):
    @app.get("/v1/_api")
    async def a():
        raise ApiError.of(409, "conflict", "Conflict.")

    @app.get("/v1/_auth")
    async def b():
        raise HTTPException(401)

    @app.get("/v1/_boom")
    async def c():
        raise RuntimeError("secret detail")

    for path, status, code in (
        ("/v1/_api", 409, "conflict"),
        ("/v1/_auth", 401, "unauthenticated"),
        ("/v1/_boom", 500, "internal_error"),
    ):
        r = await client.get(path, headers={"X-Request-ID": "rid"})
        assert r.status_code == status
        jsonschema.validate(r.json(), schema)
        assert r.json()["details"][0]["code"] == code and r.json()["request_id"] == "rid"
        assert "secret detail" not in r.text


async def test_method_not_allowed(client, schema):
    r = await client.post("/v1/healthz")
    assert r.status_code == 405
    jsonschema.validate(r.json(), schema)


async def test_cors_preflight_rejected_has_error_body(client, schema):
    r = await client.options(
        "/v1/healthz",
        headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "GET"},
    )
    assert r.status_code == 400
    jsonschema.validate(r.json(), schema)
    assert r.json()["details"][0]["code"] == "cors_rejected"
