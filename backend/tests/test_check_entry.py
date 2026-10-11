from check_helpers import adhd_prep, claim, link

from iaudit_backend.check import check_claims, check_one, passthrough_oos, stalled_draft
from iaudit_backend.llm import FailingClient, LLMUnavailable
from iaudit_backend.models import ConcernType, Verdict


def oos(cid="c0.9"):
    return claim("It is ADHD.", cid=cid, scope="out_of_scope", oos_category="diagnostic_conclusion")


def test_stalled_draft_copies_claim_fields():
    c = claim("Alex naps.", span_hint=(3, 9))
    d = stalled_draft(c, "timeout")
    assert (d.key, d.section_index, d.segments, d.span_hint) == ("c0.1", 0, c.segments, (3, 9))
    assert d.outcome == "stalled" and d.concerns == [] and d.evidence == []


def test_passthrough_oos_uses_the_atomizer_reason():
    c = oos()
    d = passthrough_oos(c)
    assert d.verdict == Verdict.out_of_scope and d.out_of_scope_reason == c.oos_reason
    assert d.concerns == [] and d.evidence == [] and d.outcome == "ok"


async def test_no_call_for_oos_stalled_and_empty(make_ctx):
    ctx = make_ctx(llm=FailingClient(LLMUnavailable("x")))  # any call would show up as a failure
    prep = adhd_prep()
    cs = [claim("Alex naps."), oos(), claim("He sleeps.", cid="c0.2"), claim("He.", cid="c0.3")]
    links = [
        link(),
        link(cid="c0.2", status="stalled", reason="timeout"),
        link(cid="c0.3", status="stalled", reason="bad_output"),
    ]
    out = await check_claims(cs, links, prep, prep.turns, ctx)
    assert [d.key for d in out] == ["c0.1", "c0.9", "c0.2", "c0.3"]
    assert out[0].verdict == Verdict.insufficient_evidence
    assert [c.type for c in out[0].concerns] == [ConcernType.unsupported_claim]
    assert out[1].verdict == Verdict.out_of_scope
    assert out[2].outcome == out[3].outcome == "stalled"
    assert ctx.metrics.records == []


async def test_missing_link_stalls_that_claim(make_ctx):
    ctx = make_ctx()
    prep = adhd_prep()
    d = await check_one(claim("Alex naps."), None, prep, prep.turns, ctx)
    assert d.outcome == "stalled"
