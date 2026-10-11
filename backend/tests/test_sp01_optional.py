"""01 optional: streaming body cap, Server-Timing, call `unit`, multiple cache breakpoints."""

import json

import pytest
from fastapi.testclient import TestClient
from pydantic import BaseModel
from test_llm import Fake, completion

from iaudit_backend.app import create_app
from iaudit_backend.config import Settings
from iaudit_backend.llm import LiteLLMClient, LLMRequest, MetricsCollector

# -- streaming body cap ----------------------------------------------------------------------


def _client(**kw):
    return TestClient(
        create_app(Settings(pipeline="stub", llm_mode="stub", **kw)), raise_server_exceptions=False
    )


async def test_body_reading_stops_once_over_the_cap():
    app = create_app(Settings(pipeline="stub", llm_mode="stub", max_body_bytes=250))
    received = 0

    async def receive():
        nonlocal received
        received += 1
        return {"type": "http.request", "body": b"x" * 100, "more_body": True}

    sent = []

    async def send(message):
        sent.append(message)

    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "POST",
        "path": "/v1/audit",
        "raw_path": b"/v1/audit",
        "query_string": b"",
        "headers": [(b"content-type", b"application/json")],  # no content-length: chunked
        "server": ("test", 80),
        "client": ("test", 1),
        "scheme": "http",
        "root_path": "",
        "app": app,
    }
    await app(scope, receive, send)
    assert sent[0]["status"] == 413
    assert received == 3  # 300 bytes crossed the 250 cap; nothing further was pulled


# -- Server-Timing ---------------------------------------------------------------------------


def test_server_timing_header_absent_by_default(example_request):
    with _client() as c:
        r = c.post("/v1/audit", json=example_request)
    assert r.status_code == 200 and "server-timing" not in r.headers


def test_server_timing_header_has_durations_only(example_request):
    with _client(server_timing=True) as c:
        r = c.post("/v1/audit", json=example_request)
    assert r.status_code == 200
    header = r.headers["server-timing"]
    assert header.startswith("total;dur=")
    for part in header.split(", "):
        name, dur = part.split(";dur=")
        assert name.isidentifier() and float(dur) >= 0


def test_server_timing_includes_stage_durations_from_the_pipeline(example_request):
    from iaudit_backend.pipeline import StubPipeline

    class Timed(StubPipeline):
        async def run(self, req, ctx):
            ctx.extras["pipeline_metrics"] = {
                "prep_ms": 5,
                "link_ms": 7,
                "calls": 3,
                "truncated": 0,
            }
            return await super().run(req, ctx)

    app = create_app(
        Settings(pipeline="stub", llm_mode="stub", server_timing=True), pipeline=Timed()
    )
    with TestClient(app) as c:
        h = c.post("/v1/audit", json=example_request).headers["server-timing"]
    assert "prep;dur=5" in h and "link;dur=7" in h and "calls" not in h


def test_server_timing_not_added_to_errors():
    with _client(server_timing=True) as c:
        r = c.post("/v1/audit", content=b"{nope")
    assert r.status_code == 400 and "server-timing" not in r.headers


# -- unit on metrics -------------------------------------------------------------------------


class Out(BaseModel):
    answer: str


def _req(**kw):
    base = dict(tier="cheap", system="sys", user="u", response_model=Out, call_tag="t")
    return LLMRequest(**{**base, **kw})


async def test_metrics_record_carries_unit():
    fake = Fake(completion('{"answer": "a"}'))
    m = MetricsCollector()
    await LiteLLMClient(Settings(llm_mode="live"), acompletion=fake).complete_json(
        _req(unit="c3"), m
    )
    assert m.snapshot()["records"][0]["unit"] == "c3"


async def test_unit_defaults_to_none():
    fake = Fake(completion('{"answer": "a"}'))
    m = MetricsCollector()
    await LiteLLMClient(Settings(llm_mode="live"), acompletion=fake).complete_json(_req(), m)
    assert m.snapshot()["records"][0]["unit"] is None


# -- cache breakpoints -----------------------------------------------------------------------


async def test_two_cache_prefixes_give_two_breakpoints():
    fake = Fake(completion('{"answer": "a"}'))
    await LiteLLMClient(Settings(llm_mode="live"), acompletion=fake).complete_json(
        _req(cache_prefixes=["ONE", "TWO"])
    )
    system = fake.calls[0]["messages"][0]["content"]
    assert [b["text"] for b in system] == ["ONE", "TWO", "sys"]
    assert [("cache_control" in b) for b in system] == [True, True, False]


async def test_more_than_two_prefixes_rejected():
    fake = Fake(completion('{"answer": "a"}'))
    with pytest.raises(ValueError):
        await LiteLLMClient(Settings(llm_mode="live"), acompletion=fake).complete_json(
            _req(cache_prefixes=["a", "b", "c"])
        )


async def test_single_cache_prefix_still_works():
    fake = Fake(completion('{"answer": "a"}'))
    await LiteLLMClient(Settings(llm_mode="live"), acompletion=fake).complete_json(
        _req(cache_prefix="P")
    )
    system = fake.calls[0]["messages"][0]["content"]
    assert json.dumps(system).count("cache_control") == 1


FIXED_KEY = "df61adfd490005e69c880a0033174adc6dd29b8b66c6da6f1496ee57290deb76"


def test_fixture_key_depends_on_cache_prefixes():
    from iaudit_backend.llm import FixtureClient

    a = FixtureClient.key_for(_req(cache_prefixes=["RULES v1", "TRANSCRIPT A"]))
    b = FixtureClient.key_for(_req(cache_prefixes=["RULES v2", "TRANSCRIPT B"]))
    assert a != b


def test_fixture_key_unchanged_when_cache_prefixes_empty():
    from iaudit_backend.llm import FixtureClient

    assert FixtureClient.key_for(_req(cache_prefix="P")) == FixtureClient.key_for(
        _req(cache_prefix="P", cache_prefixes=[])
    )
    # pinned: keys for existing recordings must not move
    assert FixtureClient.key_for(_req(cache_prefix="P")) == FIXED_KEY
