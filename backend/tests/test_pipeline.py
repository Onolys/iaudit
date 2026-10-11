import asyncio
import time

import pytest

from iaudit_backend import contract
from iaudit_backend.api.errors import DeadlineExceeded
from iaudit_backend.config import Settings
from iaudit_backend.llm import MetricsCollector, StubClient
from iaudit_backend.models import AuditRequest
from iaudit_backend.pipeline import (
    MIN_CALL_S,
    RequestContext,
    StubPipeline,
    make_pipeline,
    run_with_backstop,
)


def make_ctx(settings=None, deadline_in=60.0, request_id="r1") -> RequestContext:
    s = settings or Settings()
    return RequestContext(
        settings=s,
        llm=StubClient(),
        metrics=MetricsCollector(),
        request_id=request_id,
        deadline=time.monotonic() + deadline_in,
    )


async def test_stub_pipeline_returns_valid_empty_audit(example_request):
    req = AuditRequest.model_validate(example_request)
    resp = await StubPipeline().run(req, make_ctx(request_id=req.request_id))
    body = resp.to_json()
    assert contract.validate_response(body) == []
    assert body["claims"] == [] and body["status"] == "complete"
    assert body["request_id"] == example_request["request_id"]


async def test_stub_pipeline_omits_request_id_when_absent(example_request):
    example_request.pop("request_id")
    resp = await StubPipeline().run(AuditRequest.model_validate(example_request), make_ctx(None))
    assert "request_id" not in resp.to_json()


def test_factory():
    assert isinstance(make_pipeline(Settings(pipeline="stub")), StubPipeline)
    with pytest.raises(NotImplementedError):
        make_pipeline(Settings(pipeline="full"))


def test_context_budget():
    ctx = make_ctx(Settings(llm_timeout_s=30), deadline_in=100)
    assert ctx.call_timeout("link") == 20  # stage cap below the LLM_TIMEOUT_S ceiling
    ctx = make_ctx(Settings(llm_timeout_s=30), deadline_in=10)
    assert 9 < ctx.call_timeout("link") <= 10
    ctx = make_ctx(deadline_in=MIN_CALL_S / 2)
    assert ctx.call_timeout("link") is None
    assert ctx.remaining() <= MIN_CALL_S / 2
    assert make_ctx(deadline_in=-5).remaining() == 0


def test_fixture_scope_is_request_id():
    assert make_ctx(request_id="abc").fixture_scope == "abc"


async def test_backstop_maps_timeout(example_request):
    class Slow:
        async def run(self, req, ctx):
            await asyncio.sleep(5)

    s = Settings(audit_deadline_s=0.05)
    req = AuditRequest.model_validate(example_request)
    with pytest.raises(DeadlineExceeded):
        await run_with_backstop(Slow(), req, make_ctx(s), s, grace_s=0.01)
