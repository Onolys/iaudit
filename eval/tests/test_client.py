import json
import logging

import httpx
import pytest
from fakes.fake_backend import FakeBackend

from iaudit_eval.client import AuditClient
from iaudit_eval.paths import repo_root

EX = repo_root() / "docs" / "contracts" / "examples"


def _req(**over):
    body = json.loads((EX / "request.json").read_text(encoding="utf-8"))
    body.update(over)
    return body


class Sleeps:
    def __init__(self):
        self.calls = []

    async def __call__(self, s):
        self.calls.append(s)


def _client(fb, **kw):
    sl = Sleeps()
    kw.setdefault("sleep", sl)
    c = AuditClient("http://fake", transport=fb.transport(), **kw)
    c.sleeps = sl
    return c


async def _audit(fb, req=None, **kw):
    c = _client(fb, **kw)
    async with c:
        out = await c.audit(_req() if req is None else req)
    return out, c


async def test_ok():
    fb = FakeBackend()
    out, c = await _audit(fb)
    assert out.ok and out.status == "ok" and out.kind is None
    assert out.attempts == 1 and fb.count == 1
    assert out.response["request_id"] == "example-001"
    assert c.sleeps.calls == []


async def test_defaults():
    c = AuditClient("http://fake", transport=FakeBackend().transport())
    assert c.timeout_s == 120 and c.connect_timeout_s == 5 and c.backoff_s == 2
    await c.aclose()


@pytest.mark.parametrize("mode,code", [("429", "rate_limited"), ("503", "unavailable")])
async def test_retry_once_then_fail(mode, code):
    fb = FakeBackend(mode)
    out, c = await _audit(fb)
    assert out.status == "failed" and out.kind == "http_error"
    assert out.http_status == int(mode) and out.error_code == code
    assert out.error_message
    assert out.attempts == 2 and fb.count == 2
    assert c.sleeps.calls == [2.0]


async def test_retry_then_success():
    fb = FakeBackend(script=["429"])
    out, _ = await _audit(fb)
    assert out.ok and out.attempts == 2 and fb.count == 2


async def test_retry_502():
    def handler(request):
        handler.n += 1
        return httpx.Response(502, text="bad gateway")

    handler.n = 0
    c = AuditClient("http://fake", transport=httpx.MockTransport(handler), sleep=Sleeps())
    async with c:
        out = await c.audit(_req())
    assert handler.n == 2 and out.attempts == 2
    assert out.kind == "error_body" and out.http_status == 502


async def test_connect_error_retried():
    n = 0

    def handler(request):
        nonlocal n
        n += 1
        raise httpx.ConnectError("refused", request=request)

    c = AuditClient("http://fake", transport=httpx.MockTransport(handler), sleep=Sleeps())
    async with c:
        out = await c.audit(_req())
    assert n == 2 and out.attempts == 2
    assert out.kind == "network" and out.http_status is None


async def test_connect_timeout_is_network_retried():
    n = 0

    def handler(request):
        nonlocal n
        n += 1
        raise httpx.ConnectTimeout("slow connect", request=request)

    c = AuditClient("http://fake", transport=httpx.MockTransport(handler), sleep=Sleeps())
    async with c:
        out = await c.audit(_req())
    assert n == 2 and out.attempts == 2
    assert out.kind == "network"


async def test_no_retry_500_504():
    for mode in ("500", "504"):
        fb = FakeBackend(mode)
        out, c = await _audit(fb)
        assert out.kind == "http_error" and out.http_status == int(mode)
        assert out.attempts == 1 and fb.count == 1 and c.sleeps.calls == []


async def test_timeout_mode_no_retry():
    fb = FakeBackend("timeout")
    out, c = await _audit(fb)
    assert out.kind == "timeout" and out.attempts == 1 and fb.count == 1
    assert c.sleeps.calls == []


async def test_total_timeout_enforced():
    fb = FakeBackend(delay=1.0)
    out, _ = await _audit(fb, timeout_s=0.05)
    assert out.kind == "timeout" and out.attempts == 1 and fb.count == 1


async def test_other_transport_error_is_network_no_retry():
    n = 0

    def handler(request):
        nonlocal n
        n += 1
        raise httpx.ReadError("reset", request=request)

    c = AuditClient("http://fake", transport=httpx.MockTransport(handler), sleep=Sleeps())
    async with c:
        out = await c.audit(_req())
    assert n == 1 and out.kind == "network" and out.attempts == 1


async def test_error_body_kind_invalid_error_body():
    fb = FakeBackend("invalid_error_body")
    out, _ = await _audit(fb)
    assert out.kind == "error_body" and out.http_status == 500
    assert out.error_code is None and out.error_message is None
    assert fb.count == 1


async def test_error_body_non_json_400():
    c = AuditClient(
        "http://fake",
        transport=httpx.MockTransport(lambda r: httpx.Response(400, text="<html>x</html>")),
    )
    async with c:
        out = await c.audit(_req())
    assert out.kind == "error_body" and out.http_status == 400


async def test_backend_400_valid_error_is_http_error():
    fb = FakeBackend("unsupported_version")
    out, _ = await _audit(fb)
    assert out.kind == "http_error" and out.http_status == 400
    assert out.error_code == "unsupported_version"


async def test_invalid_request_zero_posts():
    fb = FakeBackend()
    bad = _req()
    del bad["assessment"]
    out, _ = await _audit(fb, bad)
    assert out.kind == "invalid_request" and out.attempts == 0 and fb.count == 0
    assert out.issues


async def test_invalid_response_bad_body():
    fb = FakeBackend("bad_body")
    out, _ = await _audit(fb)
    assert out.kind == "invalid_response" and out.http_status == 200 and fb.count == 1


async def test_invalid_response_schema():
    def handler(request):
        return httpx.Response(200, json={"schema_version": "0.0.1", "oops": 1})

    c = AuditClient("http://fake", transport=httpx.MockTransport(handler))
    async with c:
        out = await c.audit(_req())
    assert out.kind == "invalid_response" and out.issues


async def test_request_id_mismatch():
    fb = FakeBackend("mismatched_id")
    out, _ = await _audit(fb)
    assert out.kind == "request_id_mismatch" and out.http_status == 200
    assert out.response is None and fb.count == 1


async def test_no_request_id_skips_check():
    req = _req()
    req.pop("request_id", None)
    fb = FakeBackend()
    out, _ = await _audit(fb, req)
    assert out.ok


async def test_issues_and_logs_carry_no_text(caplog):
    secret = "ZZSECRETPHRASEZZ"
    req = _req()
    req["transcript"][0]["text"] = secret
    del req["assessment"]
    caplog.set_level(logging.DEBUG, logger="iaudit_eval")
    fb = FakeBackend()
    out, _ = await _audit(fb, req)
    fb2 = FakeBackend("429")
    out2, _ = await _audit(fb2, _req(request_id=secret))
    blob = repr(out) + repr(out2) + caplog.text
    assert secret not in blob


async def test_healthz():
    fb = FakeBackend()
    async with _client(fb) as c:
        assert await c.healthz() is True
