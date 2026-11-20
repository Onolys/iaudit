import pytest

pytestmark = pytest.mark.unit


async def test_healthz(client):
    r = await client.get("/v1/healthz")
    assert r.status_code == 200
    assert r.json() == {"status": "ok", "service_mode": "combined", "code_version": "abc123"}
    assert r.headers["x-request-id"]


async def test_cors_allowed_origin_and_headers(client):
    r = await client.options(
        "/v1/healthz",
        headers={
            "Origin": "https://app.onolys.com",
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "Authorization,X-API-Key,Idempotency-Key",
        },
    )
    assert r.status_code == 200
    assert r.headers["access-control-allow-origin"] == "https://app.onolys.com"


def test_combined_has_queue_api_does_not(settings):
    from dataclasses import replace

    from onolys_api.app import create_app

    assert create_app(settings).state.queue is not None
    assert not hasattr(create_app(replace(settings, service_mode="api")).state, "queue")
