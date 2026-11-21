"""Route-driven LiteLLM client behaviour (PRD R3 client behaviour, D13, AC5, AC9). Offline."""

import asyncio
import json
import time
from dataclasses import replace
from types import SimpleNamespace

import pytest
from pydantic import BaseModel

from onolys_core.errors import ConfigError
from onolys_core.llm import (
    LiteLLMClient,
    LLMBadOutput,
    LLMConfig,
    LLMRateLimited,
    LLMRequest,
    LLMUnavailable,
    make_client,
)
from onolys_core.llm.routes import Route


class Out(BaseModel):
    answer: str


OK = '{"answer": "ok"}'


def req(**kw) -> LLMRequest:
    base = dict(tier="mid", system="sys", user="hello", response_model=Out, call_tag="t")
    return LLMRequest(**{**base, **kw})


def completion(content=OK, finish_reason="stop"):
    return SimpleNamespace(
        choices=[
            SimpleNamespace(message=SimpleNamespace(content=content), finish_reason=finish_reason)
        ],
        usage=SimpleNamespace(prompt_tokens=1, completion_tokens=1),
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
        return r


class RateErr(Exception):
    def __init__(self, status=429, retry_after=None):
        super().__init__("rate")
        self.status_code = status
        hdrs = {} if retry_after is None else {"retry-after": str(retry_after)}
        self.response = SimpleNamespace(headers=hdrs)


def route(**kw) -> Route:
    base = dict(
        litellm_id="anthropic/claude-test",
        backoff_s=0,
        max_retries=1,
        timeout_s=30,
        max_output_tokens=500,
        max_concurrency=8,
    )
    return Route(**{**base, **kw})


def client(fake, routes=None, sleeps=None, **kw):
    cfg = LLMConfig(llm_mode="live", routes=routes or {"mid": route()}, **kw)

    async def sleep(s):
        if sleeps is not None:
            sleeps.append(s)

    return LiteLLMClient(cfg, acompletion=fake, sleep=sleep)


async def test_kwargs_come_from_route_gemini_like():
    r = route(
        litellm_id="vertex_ai/gemini-test",
        structured_output_mode="json_schema",
        caching_mode="none",
        extra_params={"vertex_location": "us-central1"},
    )
    fake = Fake(completion())
    await client(fake, {"mid": r}).complete_json(req())
    kw = fake.calls[0]
    assert kw["model"] == "vertex_ai/gemini-test"
    assert kw["response_format"]["type"] == "json_schema"
    assert kw["vertex_location"] == "us-central1"
    assert "thinking" not in kw and kw["num_retries"] == 0


async def test_max_tokens_and_timeout_default_from_route_and_clamp():
    fake = Fake(completion(), completion(), completion())
    c = client(fake)
    await c.complete_json(req())  # absent -> route values
    await c.complete_json(req(max_tokens=10_000, timeout_s=999))  # larger -> clamped
    await c.complete_json(req(max_tokens=7, timeout_s=2))  # smaller -> kept
    got = [(k["max_tokens"], k["timeout"]) for k in fake.calls]
    assert got == [(500, 30), (500, 30), (7, 2)]


async def test_temperature_omitted_when_unsupported():
    fake = Fake(completion(), completion())
    await client(fake, {"mid": route(supports_temperature=False)}).complete_json(
        req(temperature=0.0)
    )
    await client(fake, {"mid": route(supports_temperature=True)}).complete_json(
        req(temperature=0.3)
    )
    assert "temperature" not in fake.calls[0]
    assert fake.calls[1]["temperature"] == 0.3


@pytest.mark.parametrize("mode", ["none", "provider_implicit"])
async def test_prefixes_joined_into_one_string(mode):
    fake = Fake(completion())
    r = route(caching_mode=mode)
    await client(fake, {"mid": r}).complete_json(req(cache_prefixes=["ONE", "TWO"]))
    system = fake.calls[0]["messages"][0]["content"]
    assert isinstance(system, str)
    assert system.index("ONE") < system.index("TWO") < system.index("sys")
    assert "cache_control" not in json.dumps(fake.calls[0]["messages"])


async def test_prefixes_annotated_blocks_for_anthropic_ephemeral():
    fake = Fake(completion())
    r = route(caching_mode="anthropic_ephemeral")
    await client(fake, {"mid": r}).complete_json(req(cache_prefixes=["ONE", "TWO"]))
    system = fake.calls[0]["messages"][0]["content"]
    assert [b["text"] for b in system] == ["ONE", "TWO", "sys"]
    assert [("cache_control" in b) for b in system] == [True, True, False]


async def test_unknown_route_is_a_config_error():
    with pytest.raises(ConfigError, match="nope"):
        await client(Fake(completion())).complete_json(req(tier="nope"))


async def test_alias_style_routes_via_registry_default():
    # no routes given: the packaged registry is used; task aliases resolve to mid
    fake = Fake(completion())
    c = LiteLLMClient(LLMConfig(llm_mode="live"), acompletion=fake)
    await c.complete_json(req(tier="paudit_code"))
    assert fake.calls[0]["model"] == "anthropic/claude-sonnet-5-5"
    assert "temperature" not in fake.calls[0]


async def test_truncation_raises_bad_output_without_retry():
    fake = Fake(completion('{"answer": "cut', finish_reason="length"), completion())
    with pytest.raises(LLMBadOutput, match="token limit"):
        await client(fake).complete_json(req())
    assert len(fake.calls) == 1


async def test_rate_limit_waits_retry_after_and_does_not_use_max_retries():
    err = RateErr(429, retry_after=7)
    fake = Fake(err, RateErr(529), err, completion())
    sleeps: list[float] = []
    res = await client(fake, {"mid": route(max_retries=0, backoff_s=1)}, sleeps).complete_json(
        req()
    )
    assert res.parsed.answer == "ok" and len(fake.calls) == 4
    assert sleeps[0] >= 7 and sleeps[2] >= 7 and len(sleeps) == 3


async def test_rate_limit_backoff_grows_with_jitter():
    fake = Fake(*[RateErr() for _ in range(4)], completion())
    sleeps: list[float] = []
    await client(fake, {"mid": route(backoff_s=2)}, sleeps).complete_json(req())
    assert len(sleeps) == 4 and all(s > 0 for s in sleeps)
    assert sleeps[3] > sleeps[0]  # exponential (jitter keeps each step within [0.5, 1.0]x)


async def test_rate_limit_stops_at_deadline():
    fake = Fake(*[RateErr(429, retry_after=5) for _ in range(10)])
    sleeps: list[float] = []
    r = req(deadline=time.monotonic() + 3)  # retry-after exceeds what is left
    with pytest.raises(LLMRateLimited):
        await client(fake, sleeps=sleeps).complete_json(r)
    assert len(fake.calls) == 1 and sleeps == []


async def test_rate_limited_is_unavailable_and_not_retried_after_giving_up():
    assert issubclass(LLMRateLimited, LLMUnavailable)
    fake = Fake(*[RateErr(429, retry_after=5) for _ in range(5)])
    with pytest.raises(LLMRateLimited):
        await client(fake, {"mid": route(max_retries=3)}).complete_json(
            req(deadline=time.monotonic() + 1)
        )
    assert len(fake.calls) == 1


async def test_semaphore_is_per_route():
    active = {"a": 0, "b": 0}
    peak = {"a": 0, "b": 0}

    async def slow(**kw):
        k = "a" if kw["model"].endswith("-a") else "b"
        active[k] += 1
        peak[k] = max(peak[k], active[k])
        await asyncio.sleep(0.02)
        active[k] -= 1
        return completion()

    routes = {
        "ra": route(litellm_id="x/m-a", max_concurrency=2),
        "rb": route(litellm_id="x/m-b", max_concurrency=5),
    }
    c = client(slow, routes)
    await asyncio.gather(
        *(c.complete_json(req(tier="ra")) for _ in range(6)),
        *(c.complete_json(req(tier="rb")) for _ in range(10)),
    )
    assert peak == {"a": 2, "b": 5}


async def test_slow_route_does_not_block_other_route():
    release = asyncio.Event()

    async def fn(**kw):
        if kw["model"].endswith("-a"):
            await release.wait()
        return completion()

    routes = {
        "ra": route(litellm_id="x/m-a", max_concurrency=1),
        "rb": route(litellm_id="x/m-b", max_concurrency=1),
    }
    c = client(fn, routes)
    blocked = asyncio.create_task(c.complete_json(req(tier="ra")))
    await asyncio.sleep(0.01)
    res = await asyncio.wait_for(c.complete_json(req(tier="rb")), 1)
    assert res.parsed.answer == "ok"
    release.set()
    await blocked


def test_make_client_live_checks_api_keys(monkeypatch):
    monkeypatch.delenv("MY_KEY", raising=False)
    cfg = LLMConfig(llm_mode="live", routes={"mid": route(api_key_env="MY_KEY")})
    with pytest.raises(ConfigError, match="MY_KEY"):
        make_client(cfg)
    monkeypatch.setenv("MY_KEY", "x")
    assert isinstance(make_client(cfg), LiteLLMClient)


def test_make_client_stub_and_fixture_skip_key_check(monkeypatch, tmp_path):
    monkeypatch.delenv("MY_KEY", raising=False)
    routes = {"mid": route(api_key_env="MY_KEY")}
    make_client(replace(LLMConfig(llm_mode="stub"), routes=routes))
    make_client(LLMConfig(llm_mode="fixture", fixture_dir=str(tmp_path), routes=routes))
