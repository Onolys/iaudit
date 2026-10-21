import copy
import json

import pytest
from fastapi.testclient import TestClient

from iaudit_backend import contract
from iaudit_backend.app import create_app
from iaudit_backend.config import Settings
from iaudit_backend.llm.errors import LLMUnavailable


def settings(**kw) -> Settings:
    return Settings(pipeline="stub", llm_mode="stub", **kw)


@pytest.fixture
def client():
    with TestClient(create_app(settings()), raise_server_exceptions=False) as c:
        yield c


def post(client, body, headers=None):
    data = body if isinstance(body, bytes) else json.dumps(body).encode()
    h = {"content-type": "application/json", **(headers or {})}
    return client.post("/v1/audit", content=data, headers=h)


def assert_error(r, status, code, request_id=None):
    assert r.status_code == status, r.text
    body = r.json()
    assert contract.validate_error(body) == [], body
    assert body["error"]["code"] == code
    if request_id:
        assert body["request_id"] == request_id
    return body


def test_healthz(client):
    r = client.get("/healthz")
    assert r.status_code == 200 and r.json() == {"status": "ok"}


def test_ok_example(client, example_request):
    r = post(client, example_request)
    assert r.status_code == 200
    body = r.json()
    assert contract.validate_response(body) == []
    assert body["request_id"] == example_request["request_id"]
    assert body["claims"] == [] and body["status"] == "complete"


def test_turn_without_role_accepted(client, example_request):
    example_request["transcript"][0].pop("role")
    assert post(client, example_request).status_code == 200


def test_not_json_and_not_object(client):
    assert_error(post(client, b"{nope"), 400, "invalid_request")
    assert_error(post(client, b"[1,2]"), 400, "invalid_request")
    assert_error(post(client, b"\xff\xfe"), 400, "invalid_request")


def test_content_type_must_be_json(client, example_request):
    body = json.dumps(example_request).encode()
    r = post(client, body, {"content-type": "text/plain"})
    assert_error(r, 415, "invalid_request")
    assert (
        post(client, body, {"content-type": "application/json; charset=utf-8"}).status_code == 200
    )


def test_unsupported_version_before_schema(client, example_request):
    example_request["schema_version"] = "2.0.0"
    example_request["bogus"] = 1  # would also fail schema validation
    assert_error(post(client, example_request), 400, "unsupported_version", "example-001")


def test_missing_version_is_invalid_request(client, example_request):
    del example_request["schema_version"]
    assert_error(post(client, example_request), 400, "invalid_request", "example-001")


def test_schema_violation_request_id_echoed_and_no_values(client, example_request):
    example_request["transcript"][0]["text"] = 7
    example_request["transcript"][1]["speaker"] = ""
    r = post(client, example_request)
    body = assert_error(r, 400, "invalid_request", "example-001")
    assert "transcript/0/text" in body["error"]["message"]


def test_duplicate_ids_count_only(client, example_request):
    example_request["transcript"][1]["id"] = example_request["transcript"][0]["id"]
    body = assert_error(post(client, example_request), 400, "invalid_request")
    assert example_request["transcript"][0]["id"] not in body["error"]["message"]
    assert "1" in body["error"]["message"]
    dup = copy.deepcopy(example_request)
    dup["transcript"][1]["id"] = "unique-x"
    dup["assessment"].append(copy.deepcopy(dup["assessment"][0]))
    assert_error(post(client, dup), 400, "invalid_request")


def _bulk(example_request, turns=None, sections=None):
    req = copy.deepcopy(example_request)
    if turns is not None:
        req["transcript"] = [{"id": f"t{i}", "speaker": "a", "text": ""} for i in range(turns)]
    if sections is not None:
        req["assessment"] = [{"id": f"s{i}", "text": "x"} for i in range(sections)]
    return req


def test_turn_limit_boundary(example_request):
    with TestClient(create_app(settings(max_turns=5))) as c:
        assert post(c, _bulk(example_request, turns=5)).status_code == 200
        assert_error(
            post(c, _bulk(example_request, turns=6)), 413, "payload_too_large", "example-001"
        )


def test_section_limit_boundary(example_request):
    with TestClient(create_app(settings(max_sections=3))) as c:
        assert post(c, _bulk(example_request, sections=3)).status_code == 200
        assert_error(post(c, _bulk(example_request, sections=4)), 413, "payload_too_large")


def test_default_limits_2000_turns_50_sections(client, example_request):
    assert post(client, _bulk(example_request, turns=2000, sections=50)).status_code == 200
    assert_error(post(client, _bulk(example_request, turns=2001)), 413, "payload_too_large")
    assert_error(post(client, _bulk(example_request, sections=51)), 413, "payload_too_large")


def test_body_size_with_and_without_content_length(example_request):
    raw = json.dumps(example_request).encode()
    with TestClient(create_app(settings(max_body_bytes=len(raw)))) as c:
        assert post(c, raw).status_code == 200
        assert_error(post(c, raw + b" "), 413, "payload_too_large")
        # chunked: no Content-Length header, body read then checked
        r = c.post("/v1/audit", content=iter([raw, b" "]))
        assert_error(r, 413, "payload_too_large")


def test_cors(example_request):
    with TestClient(create_app(settings(cors_origins=["http://localhost:5173"]))) as c:
        ok = c.options(
            "/v1/audit",
            headers={
                "Origin": "http://localhost:5173",
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "content-type",
            },
        )
        assert ok.status_code == 200
        assert ok.headers["access-control-allow-origin"] == "http://localhost:5173"
        bad = c.options(
            "/v1/audit",
            headers={"Origin": "http://evil.test", "Access-Control-Request-Method": "POST"},
        )
        assert "access-control-allow-origin" not in bad.headers
        assert_error(bad, 400, "other")
        r = post(c, example_request, headers={"Origin": "http://localhost:5173"})
        assert r.headers["access-control-allow-origin"] == "http://localhost:5173"
    with TestClient(create_app(settings(cors_origins=["http://other.test"]))) as c:
        r = c.options(
            "/v1/audit",
            headers={"Origin": "http://localhost:5173", "Access-Control-Request-Method": "POST"},
        )
        assert "access-control-allow-origin" not in r.headers


class Raising:
    def __init__(self, exc):
        self.exc = exc

    async def run(self, req, ctx):
        raise self.exc


def test_pipeline_failures(example_request):
    cases = [
        (RuntimeError("SENTINEL"), 500, "internal_error"),
        (LLMUnavailable("x"), 503, "unavailable"),
    ]
    for exc, status, code in cases:
        app = create_app(settings(), pipeline=Raising(exc))
        with TestClient(app, raise_server_exceptions=False) as c:
            r = post(c, example_request, headers={"Origin": "http://localhost:5173"})
            assert_error(r, status, code, "example-001")
            assert "SENTINEL" not in r.text
            if status == 500:  # CORS header must survive the 500 so the UI can read it
                assert r.headers["access-control-allow-origin"] == "http://localhost:5173"


def test_deadline_backstop_504(example_request):
    import asyncio

    class Slow:
        async def run(self, req, ctx):
            await asyncio.sleep(5)

    app = create_app(settings(audit_deadline_s=0.05), pipeline=Slow(), backstop_grace_s=0.01)
    with TestClient(app) as c:
        assert_error(post(c, example_request), 504, "unavailable", "example-001")


def test_invalid_pipeline_response_is_500(example_request):
    from iaudit_backend.models import AuditResponse, Status

    class Bad:
        async def run(self, req, ctx):  # claims contradicted without evidence -> schema invalid
            from iaudit_backend.models import Claim, Pointer, Span, Verdict

            sp = Span(start=Pointer(index=0, char=0), end=Pointer(index=0, char=1))
            c = Claim(
                id="c",
                span=sp,
                verdict=Verdict.contradicted,
                explanation="e",
                concerns=[],
                evidence=[],
            )
            return AuditResponse(status=Status.complete, warnings=[], claims=[c])

    with TestClient(create_app(settings(), pipeline=Bad())) as c:
        assert_error(post(c, example_request), 500, "internal_error", "example-001")


def test_unknown_route_and_method(client):
    assert_error(client.get("/nope"), 404, "other")
    assert_error(client.get("/v1/audit"), 405, "other")


def test_startup_fails_without_contracts(tmp_path, monkeypatch):
    from iaudit_backend import contract as c

    monkeypatch.setenv("IAUDIT_CONTRACTS_DIR", str(tmp_path / "missing"))
    c.get_contracts.cache_clear()
    try:
        with pytest.raises(c.ContractError, match="contracts"):
            with TestClient(create_app(settings())):
                pass
    finally:
        monkeypatch.delenv("IAUDIT_CONTRACTS_DIR")
        c.get_contracts.cache_clear()


def test_deeply_nested_json_is_400(client):
    assert_error(post(client, b"[" * 200_000), 400, "invalid_request")


def test_previous_version_1_1_0_is_unsupported(client, example_request):
    example_request["schema_version"] = "1.1.0"
    assert_error(post(client, example_request), 400, "unsupported_version", "example-001")


def test_previous_version_1_0_0_is_unsupported(client, example_request):
    example_request["schema_version"] = "1.0.0"
    assert_error(post(client, example_request), 400, "unsupported_version", "example-001")
