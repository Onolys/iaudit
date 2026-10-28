import asyncio
import json

import httpx
import pytest
from fakes.fake_backend import FakeBackend

from iaudit_eval import contracts
from iaudit_eval.paths import repo_root

EX = repo_root() / "docs" / "contracts" / "examples"


def _req(**over):
    body = json.loads((EX / "request.json").read_text(encoding="utf-8"))
    body.update(over)
    return body


def _client(fb):
    return httpx.AsyncClient(transport=fb.transport(), base_url="http://fake")


async def _post(fb, body=None):
    async with _client(fb) as c:
        return await c.post("/v1/audit", json=_req() if body is None else body)


async def test_default_response_valid_and_echoes_id():
    fb = FakeBackend()
    r = await _post(fb)
    assert r.status_code == 200
    body = r.json()
    assert contracts.validate_response(body) == []
    assert body["request_id"] == "example-001"
    assert body["run_info"]["cost_usd"] > 0
    assert fb.count == 1 and len(fb.requests) == 1


async def test_default_valid_for_other_requests():
    fb = FakeBackend()
    for name in ("partial", "out-of-range"):
        req = json.loads((EX / f"{name}.request.json").read_text(encoding="utf-8"))
        body = (await _post(fb, req)).json()
        assert contracts.validate_response(body) == [], name


async def test_no_request_id_omitted():
    req = _req()
    del req["request_id"]
    body = (await _post(FakeBackend(), req)).json()
    assert "request_id" not in body
    assert contracts.validate_response(body) == []


async def test_healthz():
    async with _client(FakeBackend()) as c:
        r = await c.get("/healthz")
    assert r.status_code == 200 and r.json() == {"status": "ok"}


@pytest.mark.parametrize(
    "mode,status,code",
    [
        ("429", 429, "rate_limited"),
        ("503", 503, "upstream_unavailable"),
        ("504", 504, "deadline_exceeded"),
        ("500", 500, "internal_error"),
    ],
)
async def test_error_modes(mode, status, code):
    fb = FakeBackend(mode=mode)
    r = await _post(fb)
    assert r.status_code == status
    assert contracts.validate_error(r.json()) == []
    assert r.json()["details"][0]["code"] == code


async def test_429_has_retry_after_option():
    fb = FakeBackend(mode="429", retry_after="2")
    assert (await _post(fb)).headers["retry-after"] == "2"


async def test_timeout_raises():
    with pytest.raises(httpx.ReadTimeout):
        await _post(FakeBackend(mode="timeout"))


async def test_bad_body():
    r = await _post(FakeBackend(mode="bad_body"))
    assert r.status_code == 200
    with pytest.raises(ValueError):
        r.json()


async def test_invalid_error_body():
    r = await _post(FakeBackend(mode="invalid_error_body"))
    assert r.status_code >= 400
    assert contracts.validate_error(r.json())


async def test_mismatched_request_id():
    body = (await _post(FakeBackend(mode="mismatched_id"))).json()
    assert body["request_id"] != "example-001"
    assert contracts.validate_response(body) == []


async def test_missing_cost():
    body = (await _post(FakeBackend(mode="missing_cost"))).json()
    assert "cost_usd" not in body["run_info"]
    assert contracts.validate_response(body) == []


async def test_changed_models_and_prompts():
    base = (await _post(FakeBackend())).json()["run_info"]
    m = (await _post(FakeBackend(mode="changed_models"))).json()
    p = (await _post(FakeBackend(mode="changed_prompts"))).json()
    assert m["run_info"]["models"] != base["models"]
    assert m["run_info"]["prompt_hashes"] == base["prompt_hashes"]
    assert p["run_info"]["prompt_hashes"] != base["prompt_hashes"]
    assert p["run_info"]["models"] == base["models"]
    assert contracts.validate_response(m) == [] and contracts.validate_response(p) == []


async def test_invalid_request_mode():
    r = await _post(FakeBackend(mode="invalid_request"))
    assert r.status_code == 400
    assert contracts.validate_error(r.json()) == []
    assert r.json()["details"][0]["code"] == "schema_violation"


async def test_version_mismatch_detected_from_request():
    fb = FakeBackend()
    r = await _post(fb, _req(schema_version="9.8.7"))
    assert r.json()["details"][0]["code"] == "schema_violation"


async def test_probe_empty_body_semantics():
    fb = FakeBackend()
    async with _client(fb) as c:
        ok = await c.post("/v1/audit", json={"schema_version": contracts.schema_version()})
        bad = await c.post("/v1/audit", json={"schema_version": "9.8.7"})
    assert ok.status_code == 400 and ok.json()["details"][0]["code"] == "schema_violation"
    assert bad.json()["details"][0]["code"] == "schema_violation"


async def test_script_sequence_then_default():
    fb = FakeBackend(script=["503", "429"])
    codes = [(await _post(fb)).status_code for _ in range(3)]
    assert codes == [503, 429, 200]
    assert fb.count == 3


async def test_concurrency_tracking():
    fb = FakeBackend(delay=0.05)
    async with _client(fb) as c:
        await asyncio.gather(*[c.post("/v1/audit", json=_req()) for _ in range(4)])
    assert fb.max_in_flight == 4
    assert fb.in_flight == 0


async def test_invalid_json_request_is_400():
    async with _client(FakeBackend()) as c:
        r = await c.post("/v1/audit", content=b"nope")
    assert r.status_code == 400
    assert contracts.validate_error(r.json()) == []


async def test_unknown_path_404():
    async with _client(FakeBackend()) as c:
        assert (await c.get("/nope")).status_code == 404
