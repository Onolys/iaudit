"""Scaled-time latency scenarios (offline). S1 baseline, S4 failures, S5 deadline, S9 hygiene."""

import asyncio
import json
import logging
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "pipeline"))
from injector import LatencyInjector  # noqa: E402
from pl_scripted import Scripted  # noqa: E402

from iaudit_backend.llm import LLMTimeout, LLMUnavailable  # noqa: E402
from iaudit_backend.models import AuditRequest  # noqa: E402
from iaudit_backend.pipeline.full import FullPipeline  # noqa: E402

FACTOR = 1 / 50  # 60 s -> 1.2 s


def scaled(**kw):
    base = dict(
        audit_deadline_s=60 * FACTOR, assemble_reserve_s=3 * FACTOR, min_call_s=4 * FACTOR,
        cancel_grace_s=FACTOR, llm_timeout_s=30 * FACTOR,
    )  # fmt: skip
    return {**base, **kw}


async def go(make_ctx, inj, s, **kw):
    ctx = make_ctx(llm=inj, request_id="adhd-faithful", deadline_in=60 * FACTOR, **scaled(**kw))
    t0 = asyncio.get_running_loop().time()
    resp = await FullPipeline().run(AuditRequest.model_validate(s.request), ctx)
    return resp.to_json(), ctx, asyncio.get_running_loop().time() - t0


def test_injector_latencies_are_scaled_and_reproducible():
    a, b = LatencyInjector(None, seed=1), LatencyInjector(None, seed=1)
    xs = [a.delay("link") for _ in range(50)]
    assert xs == [b.delay("link") for _ in range(50)]
    assert 0.04 < sorted(xs)[25] < 0.16  # p50 near 4 s * (1/50) = 0.08 s
    assert LatencyInjector(None).delay("unknown") == 0.0


async def test_s1_baseline_pipelines_stages_within_the_deadline(make_ctx):
    s = Scripted()
    inj = LatencyInjector(s)
    body, ctx, took = await go(make_ctx, inj, s)
    assert body["status"] == "complete" and len(body["claims"]) == 11
    assert took < 60 * FACTOR
    # pipelining: the first link call starts right after atomize ends, checks follow links
    assert min(inj.starts("link")) >= max(inj.ends("atomize")) - 1e-3
    assert min(inj.starts("check")) > min(inj.starts("link"))
    assert inj.peak <= 20
    assert ctx.metrics.snapshot()["counters"]["deadline_hit"] == 0


@pytest.mark.parametrize(
    "tag,exc,expect",
    [
        ("link", LLMTimeout("t"), "claim"),
        ("check", LLMUnavailable("u"), "claim"),
        ("atomize", LLMTimeout("t"), "nothing"),
    ],
)
async def test_s4_failure_injection(make_ctx, tag, exc, expect):
    s = Scripted()
    unit = None if tag == "atomize" else "c0.1"
    inj = LatencyInjector(s, latencies={}, failures={(tag, unit): exc})
    if expect == "nothing":
        from iaudit_backend.api.errors import DeadlineExceeded

        with pytest.raises(DeadlineExceeded):  # the only section failed: 504, not an empty audit
            await go(make_ctx, inj, s)
        return
    body, _, _ = await go(make_ctx, inj, s)
    assert body["status"] == "complete"
    verdicts = [c["verdict"] for c in body["claims"]]
    assert verdicts.count("insufficient_evidence") >= 1 and len(verdicts) == 11
    assert any(w["code"] == "other" for w in body["warnings"])


async def test_s5_deadline_overrun_returns_in_time_without_leaking_tasks(make_ctx):
    s = Scripted()
    slow_check = {"atomize": (0, 0), "link": (0, 0), "check": (500, 600)}  # check never fits
    inj = LatencyInjector(s, latencies=slow_check)
    before = len(asyncio.all_tasks())
    from iaudit_backend.api.errors import DeadlineExceeded

    ctx = make_ctx(llm=inj, request_id="r", deadline_in=60 * FACTOR, **scaled())
    t0 = asyncio.get_running_loop().time()
    with pytest.raises(DeadlineExceeded):
        await FullPipeline().run(AuditRequest.model_validate(s.request), ctx)
    assert asyncio.get_running_loop().time() - t0 < 60 * FACTOR + 0.5 * FACTOR * 10
    await asyncio.sleep(0.05)
    assert len(asyncio.all_tasks()) == before
    assert ctx.metrics.snapshot()["counters"]["deadline_hit"] == 1


async def test_s9_sentinel_text_never_reaches_logs_metrics_or_headers(make_ctx, caplog):
    from fastapi.testclient import TestClient

    from iaudit_backend.app import create_app
    from iaudit_backend.config import Settings

    s = Scripted()
    body = json.loads(json.dumps(s.request))
    body["transcript"][0]["text"] = body["transcript"][0]["text"] + " ZEBRASENTINEL"
    app = create_app(Settings(pipeline="full", llm_mode="stub", server_timing=True), llm=s)
    with caplog.at_level(logging.DEBUG), TestClient(app) as c:
        r = await asyncio.to_thread(c.post, "/v1/audit", json=body)
    assert r.status_code == 200, r.text
    assert "ZEBRASENTINEL" not in caplog.text
    assert "ZEBRASENTINEL" not in json.dumps(dict(r.headers))
    assert "total;dur=" in r.headers["server-timing"]
    assert "run_info" in r.json()
    assert "ZEBRASENTINEL" not in json.dumps(r.json()["run_info"])
