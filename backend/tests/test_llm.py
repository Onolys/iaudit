import asyncio
import json
import time
from types import SimpleNamespace

import pytest
from pydantic import BaseModel

from iaudit_backend.config import Settings
from iaudit_backend.llm import (
    FailingClient,
    FixtureClient,
    LiteLLMClient,
    LLMRequest,
    MetricsCollector,
    StubClient,
    make_client,
)
from iaudit_backend.llm.errors import (
    FixtureMiss,
    LLMBadOutput,
    LLMTimeout,
    LLMUnavailable,
)


class Out(BaseModel):
    answer: str


def req(**kw) -> LLMRequest:
    base = dict(tier="cheap", system="sys", user="hello", response_model=Out, call_tag="t")
    base.update(kw)
    return LLMRequest(**base)


def completion(content: str, **usage):
    u = dict(prompt_tokens=10, completion_tokens=5, cache_read_input_tokens=3)
    u.update(usage)
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=content))],
        usage=SimpleNamespace(**u),
    )


class Fake:
    def __init__(self, *results):
        self.results = list(results)
        self.calls: list[dict] = []

    async def __call__(self, **kwargs):
        self.calls.append(kwargs)
        r = self.results.pop(0)
        if isinstance(r, BaseException):
            raise r
        if callable(r):
            return await r()
        return r


def settings(**kw):
    return Settings(llm_mode="live", **kw)


async def test_success_captures_usage_and_latency():
    fake = Fake(completion('{"answer": "ok"}'))
    m = MetricsCollector()
    res = await LiteLLMClient(settings(), acompletion=fake).complete_json(req(), m)
    assert res.parsed == Out(answer="ok")
    assert res.usage.input_tokens == 10 and res.usage.output_tokens == 5
    assert res.usage.cache_read_tokens == 3
    assert res.attempts == 1 and res.latency_ms >= 0
    kw = fake.calls[0]
    assert kw["num_retries"] == 0 and kw["model"] == settings().model_cheap
    assert kw["response_format"] == {"type": "json_object"}
    assert kw["drop_params"] is True
    assert kw["thinking"] == {"type": "disabled"}
    snap = m.snapshot()
    assert snap["calls"] == 1 and snap["by_tier"]["cheap"]["input_tokens"] == 10
    assert "hello" not in json.dumps(snap)


async def test_json_schema_format_is_opt_in():
    fake = Fake(completion('{"answer": "ok"}'))
    await LiteLLMClient(
        settings(llm_response_format="json_schema"), acompletion=fake
    ).complete_json(req())
    rf = fake.calls[0]["response_format"]
    assert rf["type"] == "json_schema" and rf["json_schema"]["strict"] is True


async def test_cache_control_present_only_with_prefix():
    fake = Fake(completion('{"answer": "a"}'), completion('{"answer": "a"}'))
    c = LiteLLMClient(settings(), acompletion=fake)
    await c.complete_json(req(cache_prefix="PREFIX"))
    await c.complete_json(req())
    assert "cache_control" in json.dumps(fake.calls[0]["messages"])
    assert "cache_control" not in json.dumps(fake.calls[1]["messages"])


async def test_fenced_json_reply_is_accepted():
    fake = Fake(completion('```json\n{"answer": "ok"}\n```'))
    res = await LiteLLMClient(settings(), acompletion=fake).complete_json(req())
    assert res.parsed == Out(answer="ok") and res.attempts == 1


async def test_bad_json_retries_once_then_raises():
    fake = Fake(completion("not json"), completion('{"wrong": 1}'))
    with pytest.raises(LLMBadOutput):
        await LiteLLMClient(settings(), acompletion=fake).complete_json(req())
    assert len(fake.calls) == 2


async def test_bad_json_then_good():
    fake = Fake(completion("nope"), completion('{"answer": "x"}'))
    res = await LiteLLMClient(settings(), acompletion=fake).complete_json(req())
    assert res.attempts == 2 and res.parsed.answer == "x"


async def test_timeout_one_retry():
    async def hang():
        await asyncio.sleep(5)

    fake = Fake(hang, hang)
    m = MetricsCollector()
    with pytest.raises(LLMTimeout):
        await LiteLLMClient(settings(), acompletion=fake).complete_json(req(timeout_s=0.05), m)
    assert len(fake.calls) == 2
    assert m.records[0]["ok"] is False and m.records[0]["attempts"] == 2


async def test_retry_is_deadline_gated():
    fake = Fake(ConnectionError("x"), completion('{"answer": "x"}'))
    r = req(timeout_s=10, deadline=time.monotonic() + 1)  # not enough room for another call
    with pytest.raises(LLMUnavailable):
        await LiteLLMClient(settings(), acompletion=fake).complete_json(r)
    assert len(fake.calls) == 1


async def test_auth_error_not_retried():
    import litellm

    err = litellm.AuthenticationError("bad key", "anthropic", "m")
    fake = Fake(err, completion('{"answer": "x"}'))
    with pytest.raises(LLMUnavailable):
        await LiteLLMClient(settings(), acompletion=fake).complete_json(req())
    assert len(fake.calls) == 1


async def test_cancel_is_not_swallowed():
    started = asyncio.Event()

    async def hang():
        started.set()
        await asyncio.sleep(5)

    fake = Fake(hang)
    task = asyncio.create_task(LiteLLMClient(settings(), acompletion=fake).complete_json(req()))
    await started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


async def test_semaphore_limits_concurrency():
    active = peak = 0

    async def slow(**_):
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        await asyncio.sleep(0.02)
        active -= 1
        return completion('{"answer": "x"}')

    c = LiteLLMClient(settings(llm_max_concurrency=2), acompletion=slow)
    await asyncio.gather(*(c.complete_json(req()) for _ in range(6)))
    assert peak == 2


async def test_fixture_hit_miss_and_explicit_key(tmp_path):
    c = FixtureClient(tmp_path)
    with pytest.raises(FixtureMiss):
        await c.complete_json(req())
    key = FixtureClient.key_for(req())
    (tmp_path / f"{key}.json").write_text('{"answer": "hit"}')
    assert (await c.complete_json(req())).parsed.answer == "hit"
    (tmp_path / "my-key.json").write_text('{"answer": "explicit"}')
    assert (await c.complete_json(req(fixture_key="my-key"))).parsed.answer == "explicit"
    with pytest.raises(FixtureMiss):
        await c.complete_json(req(fixture_key="../escape"))


async def test_stub_and_failing():
    s = StubClient()
    s.register("t", Out(answer="canned"))
    assert (await s.complete_json(req())).parsed.answer == "canned"
    with pytest.raises(FixtureMiss):
        await s.complete_json(req(call_tag="other"))
    with pytest.raises(LLMTimeout):
        await FailingClient(LLMTimeout("x")).complete_json(req())


def test_make_client_modes(tmp_path):
    assert isinstance(make_client(Settings(llm_mode="stub")), StubClient)
    assert isinstance(
        make_client(Settings(llm_mode="fixture", fixture_dir=str(tmp_path))), FixtureClient
    )
    assert isinstance(make_client(Settings(llm_mode="live")), LiteLLMClient)
