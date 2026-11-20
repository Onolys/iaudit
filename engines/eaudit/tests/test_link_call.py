import asyncio

import pytest
from atomize_helpers import FIXTURES, ROSTER, adhd_section
from link_helpers import adhd_prep, adhd_turns, claim

from eaudit.atomize import atomize_section
from eaudit.atomize.prompt import Speaker
from eaudit.link.context import build_link_context
from eaudit.link.linker import link_one
from eaudit.link.models import LinkerOutput
from eaudit.llm import (
    FailingClient,
    FixtureClient,
    LLMBadOutput,
    LLMResult,
    LLMTimeout,
    LLMUnavailable,
    StubClient,
)


def out(*items):
    return {"items": list(items)}


def item(key="e1", turn=3, text="Most meetings.", role="supporting", lt="quote", **kw):
    return {
        "key": key,
        "role": role,
        "link_type": lt,
        "segments": [{"turn": turn, "text": text}],
        **kw,
    }


def stub(output, capture=None):
    c = StubClient()

    def fn(req):
        if capture is not None:
            capture.append(req)
        return LinkerOutput.model_validate(output)

    c.register("link", fn)
    return c


def lctx(ctx):
    return build_link_context(adhd_turns(), adhd_prep(), ctx)


async def adhd_claims(make_ctx):
    ctx = make_ctx(llm=FixtureClient(FIXTURES), request_id="adhd-faithful")
    roster = [*ROSTER, Speaker("sam1", "informant")]
    return (await atomize_section(adhd_section(), roster, ctx, index=0)).claims


async def test_fixture_replay_parses_for_adhd_claims(make_ctx):
    claims = await adhd_claims(make_ctx)
    ctx = make_ctx(llm=FixtureClient(FIXTURES), request_id="adhd-faithful", link_mode="shortlist")
    lc = lctx(ctx)
    results = [await link_one(c, lc, ctx) for c in (claims[0], claims[1], claims[10])]
    assert [r.claim_id for r in results] == ["c0.1", "c0.2", "c0.11"]
    assert all(r.status == "ok" and len(r.evidence) == 1 for r in results)
    assert results[0].evidence[0].draft.segments[0].turn_index == 3
    assert results[0].evidence[0].draft.key == "c0.1:e1"
    assert results[2].mode == "shortlist" and 5 in results[2].shortlist


async def test_request_shape_whole_and_shortlist(make_ctx):
    for mode in ("whole", "shortlist"):
        seen: list = []
        ctx = make_ctx(llm=stub(out(), seen), link_mode=mode)
        await link_one(claim("Alex loses attention in most meetings."), lctx(ctx), ctx)
        (req,) = seen
        assert (req.tier, req.call_tag, req.temperature) == ("mid", "link", 0.0)
        assert req.response_model is LinkerOutput and req.max_tokens == 1200
        assert req.deadline == ctx.deadline and 0 < req.timeout_s <= ctx.settings.llm_timeout_s
        assert req.fixture_key == "r1.link.c0.1"
        assert ("# Transcript" in req.cache_prefix) == (mode == "whole")


async def test_whole_mode_cache_prefix_identical_across_claims(make_ctx):
    seen: list = []
    ctx = make_ctx(llm=stub(out(), seen), link_mode="whole")
    lc = lctx(ctx)
    await link_one(claim("Alex naps."), lc, ctx)
    await link_one(claim("He forgets things.", cid="c0.2"), lc, ctx)
    assert seen[0].cache_prefix == seen[1].cache_prefix and seen[0].user != seen[1].user


async def test_out_of_scope_claims_make_no_call(make_ctx):
    seen: list = []
    ctx = make_ctx(llm=stub(out(), seen))
    c = claim("It is a diagnosis.", scope="out_of_scope", oos_category="diagnostic_conclusion")
    r = await link_one(c, lctx(ctx), ctx)
    assert seen == [] and (r.status, r.evidence) == ("ok", [])


async def test_empty_items_is_ok_with_no_evidence(make_ctx):
    ctx = make_ctx(llm=stub(out()), link_mode="shortlist")
    r = await link_one(claim("Alex loses attention in meetings."), lctx(ctx), ctx)
    assert (r.status, r.reason, r.evidence) == ("ok", None, [])


@pytest.mark.parametrize(
    "exc,reason",
    [
        (LLMTimeout("t"), "timeout"),
        (LLMUnavailable("u"), "unavailable"),
        (LLMBadOutput("b"), "bad_output"),
    ],
)
async def test_llm_errors_stall_the_claim(make_ctx, exc, reason):
    ctx = make_ctx(llm=FailingClient(exc))
    r = await link_one(claim("Alex naps."), lctx(ctx), ctx)
    assert (r.status, r.reason, r.evidence) == ("stalled", reason, [])


async def test_no_call_when_budget_is_exhausted(make_ctx):
    seen: list = []
    ctx = make_ctx(llm=stub(out(), seen), deadline_in=0.5)
    r = await link_one(claim("Alex naps."), lctx(ctx), ctx)
    assert seen == [] and (r.status, r.reason) == ("stalled", "timeout")


async def test_local_semaphore_bounds_in_flight_calls(make_ctx):
    live = peak = 0

    class Client:
        async def complete_json(self, req, metrics=None):
            nonlocal live, peak
            live += 1
            peak = max(peak, live)
            await asyncio.sleep(0.01)
            live -= 1
            return LLMResult(parsed=LinkerOutput(items=[]))

    ctx = make_ctx(llm=Client(), link_concurrency=2)
    lc = lctx(ctx)
    await asyncio.gather(
        *(link_one(claim(f"Claim {i}.", cid=f"c0.{i}"), lc, ctx) for i in range(6))
    )
    assert peak == 2
