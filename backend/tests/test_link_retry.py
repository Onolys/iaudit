import asyncio

from link_helpers import adhd_prep, adhd_turns, claim

from iaudit_backend.link.context import build_link_context
from iaudit_backend.link.linker import link_one
from iaudit_backend.link.models import LinkerOutput
from iaudit_backend.llm import LLMBadOutput, LLMResult, LLMTimeout, LLMUnavailable

GOOD = {
    "items": [
        {
            "key": "e1",
            "role": "supporting",
            "link_type": "quote",
            "segments": [{"turn": 7, "text": "My phone, constantly."}],
        }
    ]
}
BAD = {  # nothing validates: text not in turn 7... and turn outside shortlist
    "items": [
        {
            "key": "e1",
            "role": "supporting",
            "link_type": "quote",
            "segments": [{"turn": 3, "text": "totally invented words here"}],
        },
        {
            "key": "e2",
            "role": "supporting",
            "link_type": "quote",
            "segments": [{"turn": 99, "text": "x y"}],
        },
    ]
}


class Script:
    def __init__(self, *items):
        self.items, self.requests = list(items), []

    async def complete_json(self, req, metrics=None):
        self.requests.append(req)
        item = self.items[min(len(self.requests), len(self.items)) - 1]
        if isinstance(item, Exception):
            raise item
        return LLMResult(parsed=LinkerOutput.model_validate(item))


async def go(make_ctx, client, text="Alex misplaces his phone daily.", cid="c0.1", **kw):
    ctx = make_ctx(llm=client, link_mode="whole", **kw)
    lc = build_link_context(adhd_turns(), adhd_prep(), ctx)
    return await link_one(claim(text, cid=cid), lc, ctx)


async def test_valid_output_makes_one_call(make_ctx):
    client = Script(GOOD)
    r = await go(make_ctx, client)
    assert r.status == "ok" and len(client.requests) == 1 and len(r.evidence) == 1
    assert r.ambiguous_turns == [7] and r.counts["items_kept"] == 1


async def test_all_items_dropped_then_valid_retry_succeeds_with_exactly_one_retry(make_ctx):
    client = Script(BAD, GOOD)
    r = await go(make_ctx, client)
    assert r.status == "ok" and len(client.requests) == 2 and len(r.evidence) == 1
    assert r.counts["retries"] == 1
    retry = client.requests[1]
    assert retry.fixture_key == "r1.link.c0.1.retry"
    assert "not_in_shortlist: 1" in retry.user and "unlocatable: 1" in retry.user
    assert "invented" not in retry.user.split("Problems")[-1]


async def test_retry_passes_the_deadline(make_ctx):
    client = Script(BAD, GOOD)
    ctx = make_ctx(llm=client, link_mode="whole")
    lc = build_link_context(adhd_turns(), adhd_prep(), ctx)
    await link_one(claim("Alex phone."), lc, ctx)
    assert all(q.deadline == ctx.deadline for q in client.requests)


async def test_still_all_dropped_after_retry_stalls(make_ctx):
    client = Script(BAD, BAD)
    r = await go(make_ctx, client)
    assert (r.status, r.reason, r.evidence) == ("stalled", "all_dropped", [])
    assert len(client.requests) == 2


async def test_empty_items_is_ok_and_never_retried(make_ctx):
    client = Script({"items": []}, GOOD)
    r = await go(make_ctx, client)
    assert (r.status, r.evidence) == ("ok", []) and len(client.requests) == 1


async def test_partial_drops_are_not_retried(make_ctx):
    mixed = {"items": [*GOOD["items"], *BAD["items"]]}
    client = Script(mixed, GOOD)
    r = await go(make_ctx, client)
    assert r.status == "ok" and len(client.requests) == 1 and len(r.evidence) == 1


async def test_retry_skipped_under_low_budget(make_ctx):
    client = Script(BAD, GOOD)
    r = await go(make_ctx, client, deadline_in=10.0)  # < llm_timeout_s
    assert (r.status, r.reason) == ("stalled", "all_dropped") and len(client.requests) == 1


async def test_retry_can_be_disabled(make_ctx):
    client = Script(BAD, GOOD)
    r = await go(make_ctx, client, link_retry=False)
    assert r.status == "stalled" and len(client.requests) == 1


async def test_retry_call_failure_stalls_with_that_reason(make_ctx):
    r = await go(make_ctx, Script(BAD, LLMUnavailable("down")))
    assert (r.status, r.reason) == ("stalled", "unavailable")
    r = await go(make_ctx, Script(BAD, LLMTimeout("slow")))
    assert r.reason == "timeout"
    r = await go(make_ctx, Script(BAD, LLMBadOutput("junk")))
    assert r.reason == "bad_output"


async def test_one_stalled_claim_while_others_link(make_ctx):
    class Mixed:
        def __init__(self):
            self.n = 0

        async def complete_json(self, req, metrics=None):
            if "doomed" in req.user:
                raise LLMUnavailable("x")
            return LLMResult(parsed=LinkerOutput.model_validate(GOOD))

    ctx = make_ctx(llm=Mixed(), link_mode="whole")
    lc = build_link_context(adhd_turns(), adhd_prep(), ctx)
    rs = await asyncio.gather(
        link_one(claim("fine one", cid="c0.1"), lc, ctx),
        link_one(claim("doomed one", cid="c0.2"), lc, ctx),
        link_one(claim("fine two", cid="c0.3"), lc, ctx),
    )
    assert [r.status for r in rs] == ["ok", "stalled", "ok"]
    assert rs[1].reason == "unavailable" and rs[0].evidence and rs[2].evidence


async def test_validated_evidence_replaces_raw_conversion(make_ctx):
    # segment text is not in turn 3 -> dropped by validation; GOOD item survives
    mixed = {"items": [BAD["items"][0], {**GOOD["items"][0], "key": "e2"}]}
    r = await go(make_ctx, Script(mixed))
    assert [e.draft.key for e in r.evidence] == ["c0.1:e1"]
    assert r.evidence[0].draft.segments[0].turn_index == 7
