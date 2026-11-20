"""06 optional: shared cache layout, t=0 warm-up, rich metrics."""

import asyncio

import pytest
from pl_scripted import Scripted

from eaudit.llm import LLMRequest, LLMResult, LLMUnavailable, MetricsCollector, Usage
from eaudit.models import AuditRequest
from eaudit.pipeline.full import FullPipeline
from eaudit.pipeline.layout import COMMON_SYSTEM, transcript_prefix
from eaudit.prep import index_turns


class Spy(Scripted):
    """Scripted plus a record of every request; answers warm-up calls with a tiny object."""

    def __init__(self, *a, warm_delay=0.0, warm_error=None, **kw):
        super().__init__(*a, **kw)
        self.reqs: list[LLMRequest] = []
        self.order: list[str] = []
        self.warm_delay, self.warm_error = warm_delay, warm_error

    async def complete_json(self, req, metrics=None):
        self.reqs.append(req)
        self.order.append(req.call_tag)
        if req.call_tag == "warmup":
            await asyncio.sleep(self.warm_delay)
            if self.warm_error:
                raise self.warm_error
            return LLMResult(parsed=req.response_model(ok=True))
        return await super().complete_json(req, metrics)

    def tagged(self, tag):
        return [r for r in self.reqs if r.call_tag == tag]


async def run(make_ctx, s, **kw):
    ctx = make_ctx(llm=s, request_id="adhd-faithful", **kw)
    resp = await FullPipeline().run(AuditRequest.model_validate(s.request), ctx)
    return resp.to_json(), ctx


SHARED = dict(cache_layout="shared", link_mode="whole")
WARM = dict(**SHARED, cache_warmup=True, cache_min_prefix_tokens=10)


# -- layout ----------------------------------------------------------------------------------


def test_transcript_prefix_is_the_same_for_plain_and_indexed_turns():
    from link_helpers import adhd_turns

    turns = adhd_turns()
    assert transcript_prefix(turns) == transcript_prefix(index_turns(turns))
    assert transcript_prefix(turns).startswith(COMMON_SYSTEM)


async def test_default_layout_keeps_one_cache_prefix_per_stage(make_ctx):
    s = Spy()
    await run(make_ctx, s, link_mode="whole")
    assert all(r.cache_prefixes == [] for r in s.tagged("link") + s.tagged("check"))


async def test_shared_layout_gives_link_and_check_the_same_transcript_prefix(make_ctx):
    s = Spy()
    body, _ = await run(make_ctx, s, **SHARED)
    reqs = s.tagged("link") + s.tagged("check")
    assert len(reqs) == 22 and body["status"] == "complete"
    assert len({r.cache_prefixes[0] for r in reqs}) == 1  # byte-identical prefix 1
    assert len({r.system for r in reqs}) == 1 and all(r.cache_prefix is None for r in reqs)
    link_stage = {r.cache_prefixes[1] for r in s.tagged("link")}
    check_stage = {r.cache_prefixes[1] for r in s.tagged("check")}
    assert len(link_stage) == len(check_stage) == 1 and link_stage != check_stage
    assert all(r.user.startswith("Claim:") for r in reqs)  # claim block last, outside the prefix


async def test_shared_layout_in_shortlist_mode_keeps_per_stage_prefixes(make_ctx):
    s = Spy()
    await run(make_ctx, s, cache_layout="shared", link_mode="shortlist")
    reqs = s.tagged("link") + s.tagged("check")
    assert all(len(r.cache_prefixes) == 0 and r.cache_prefix for r in reqs)


# -- warm-up ---------------------------------------------------------------------------------


async def test_warmup_primes_the_exact_prefixes_the_stages_use(make_ctx):
    s = Spy()
    await run(make_ctx, s, **WARM)
    warm = s.tagged("warmup")
    assert len(warm) == 3
    step1 = [w for w in warm if len(w.cache_prefixes) == 1]
    step2 = [w for w in warm if len(w.cache_prefixes) == 2]
    assert len(step1) == 1 and len(step2) == 2
    p1 = s.tagged("link")[0].cache_prefixes[0]
    assert step1[0].cache_prefixes[0] == p1 and all(w.cache_prefixes[0] == p1 for w in step2)
    assert {w.cache_prefixes[1] for w in step2} == {
        s.tagged("link")[0].cache_prefixes[1],
        s.tagged("check")[0].cache_prefixes[1],
    }
    assert all(w.max_tokens == 1 and w.tier == "mid" and not w.retry for w in warm)


async def test_warmup_finishes_before_the_first_link_call(make_ctx):
    s = Spy(warm_delay=0.05)
    await run(make_ctx, s, **WARM)
    first_link = s.order.index("link")
    assert s.order[:first_link].count("warmup") == 3


async def test_warmup_is_skipped_for_short_transcripts(make_ctx):
    s = Spy()
    await run(make_ctx, s, cache_layout="shared", link_mode="whole", cache_warmup=True)
    assert s.tagged("warmup") == []  # the ADHD example is far below 1024 tokens


@pytest.mark.parametrize("mode", ["fixture", "stub"])
async def test_warmup_never_runs_outside_live_mode(make_ctx, mode):
    s = Spy()
    await run(make_ctx, s, llm_mode=mode, **WARM)
    assert s.tagged("warmup") == []


async def test_warmup_is_off_by_default(make_ctx):
    s = Spy()
    await run(make_ctx, s, **SHARED, cache_min_prefix_tokens=10)
    assert s.tagged("warmup") == []


async def test_shortlist_mode_warms_the_two_stage_prefixes_in_parallel(make_ctx):
    s = Spy()
    await run(
        make_ctx, s, cache_layout="shared", link_mode="shortlist", cache_warmup=True,
        cache_min_prefix_tokens=10, llm_mode="live",
    )  # fmt: skip
    warm = s.tagged("warmup")
    assert len(warm) == 2 and all(w.cache_prefix and not w.cache_prefixes for w in warm)
    used = {r.cache_prefix for r in s.tagged("link") + s.tagged("check")}
    assert {w.cache_prefix for w in warm} <= used


async def test_warmup_failure_is_ignored(make_ctx):
    s = Spy(warm_error=LLMUnavailable("down"))
    body, ctx = await run(make_ctx, s, **WARM)
    assert body["status"] == "complete" and len(body["claims"]) == 11
    assert len(s.tagged("warmup")) >= 1


async def test_flows_stop_waiting_for_a_slow_warmup(make_ctx):
    s = Spy(warm_delay=5)
    ctx_kw = dict(WARM, warmup_max_wait_s=0.05)
    started = asyncio.get_running_loop().time()
    body, _ = await run(make_ctx, s, **ctx_kw)
    assert asyncio.get_running_loop().time() - started < 3
    assert body["status"] == "complete" and len(s.tagged("link")) == 11


async def test_a_prefix_cache_fake_sees_every_stage_prefix_before_its_first_use(make_ctx):
    s = Spy()
    await run(make_ctx, s, **WARM)
    seen: set[str] = set()
    misses = 0
    for r in s.reqs:
        key = "|".join(r.cache_prefixes)
        if r.call_tag in ("link", "check") and key not in seen:
            misses += 1
        if r.cache_prefixes:
            seen.add("|".join(r.cache_prefixes))
            seen.add(r.cache_prefixes[0])
    assert misses == 0


# -- rich metrics ----------------------------------------------------------------------------


def test_cache_hit_ratio_and_error_kind_in_the_snapshot():
    m = MetricsCollector()
    req = LLMRequest(
        tier="cheap", system="s", user="u", response_model=Spy, call_tag="t", unit="c1"
    )
    m.record(req, "m", Usage(input_tokens=80, cache_read_tokens=20), 5.0, 1, True)
    m.record(req, "m", Usage(), 5.0, 2, False, error_kind="timeout")
    snap = m.snapshot()
    assert snap["cache_hit_ratio"] == pytest.approx(0.2)
    assert [r["error_kind"] for r in snap["records"]] == [None, "timeout"]
    assert snap["records"][0]["unit"] == "c1"


def test_cache_hit_ratio_is_zero_without_tokens():
    assert MetricsCollector().snapshot()["cache_hit_ratio"] == 0.0


async def test_pipeline_fills_stage_spans_and_counters_in_the_snapshot(make_ctx):
    s = Scripted()
    ctx = make_ctx(llm=s, request_id="r")
    await FullPipeline().run(AuditRequest.model_validate(s.request), ctx)
    snap = ctx.metrics.snapshot()
    stages = snap["stages"]
    assert set(stages) == {"prep", "atomize", "link", "check"}
    for st in stages.values():
        assert set(st) == {"first_start_ms", "last_end_ms", "calls", "over_budget"}
        assert 0 <= st["first_start_ms"] <= st["last_end_ms"] and st["over_budget"] is False
    assert stages["atomize"]["calls"] == 1 and stages["link"]["calls"] == 11
    c = snap["counters"]
    assert c["claims_in_scope"] == 11 and c["sections_ok"] == 1 and c["deadline_hit"] == 0
    assert c["remaining_ms_at_assemble"] > 0
