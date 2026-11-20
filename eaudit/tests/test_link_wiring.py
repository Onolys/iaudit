import asyncio
import logging

from atomize_helpers import FIXTURES, ROSTER, adhd_section
from link_helpers import adhd_prep, adhd_turns, claim

from eaudit.assembler import ClaimDraft, InternalAudit, assemble
from eaudit.atomize import atomize_section
from eaudit.atomize.prompt import Speaker
from eaudit.contract import validate_response
from eaudit.link import link_claims, to_evidence_drafts
from eaudit.link.models import LinkerOutput
from eaudit.llm import FailingClient, FixtureClient, LLMResult, LLMUnavailable
from eaudit.models import AuditRequest
from eaudit.prep import prep as run_prep

GOOD = {
    "items": [
        {
            "key": "e1",
            "role": "supporting",
            "link_type": "quote",
            "segments": [{"turn": 7, "text": "My phone, constantly."}],
            "note": "Daily loss.",
        }
    ]
}


class Counting:
    def __init__(self, output=GOOD, delay=0.0, fail_on=None):
        self.calls, self.live, self.peak = 0, 0, 0
        self.output, self.delay, self.fail_on = output, delay, fail_on

    async def complete_json(self, req, metrics=None):
        self.calls += 1
        self.live += 1
        self.peak = max(self.peak, self.live)
        try:
            await asyncio.sleep(self.delay)
            if self.fail_on and self.fail_on in req.user:
                raise LLMUnavailable("down")
            return LLMResult(parsed=LinkerOutput.model_validate(self.output))
        finally:
            self.live -= 1


async def test_in_scope_claims_make_one_call_each_oos_make_none(make_ctx):
    client = Counting()
    ctx = make_ctx(llm=client)
    claims = [
        claim("Claim one.", cid="c0.1"),
        claim(
            "A diagnosis.", cid="c0.2", scope="out_of_scope", oos_category="diagnostic_conclusion"
        ),
        claim("Claim three.", cid="c0.3"),
    ]
    out = await link_claims(claims, adhd_prep(), adhd_turns(), ctx)
    assert client.calls == 2 and [r.claim_id for r in out] == ["c0.1", "c0.2", "c0.3"]
    assert out[1].evidence == [] and out[1].status == "ok"


async def test_up_to_twenty_in_flight(make_ctx):
    client = Counting(delay=0.02)
    ctx = make_ctx(llm=client, link_concurrency=20)
    claims = [claim(f"Claim {i}.", cid=f"c0.{i}") for i in range(1, 31)]
    await link_claims(claims, adhd_prep(), adhd_turns(), ctx)
    assert client.calls == 30 and 1 < client.peak <= 20


async def test_per_claim_failures_never_raise_and_others_link(make_ctx):
    client = Counting(fail_on="doomed")
    ctx = make_ctx(llm=client)
    claims = [claim("fine", cid="c0.1"), claim("doomed", cid="c0.2"), claim("fine too", cid="c0.3")]
    out = await link_claims(claims, adhd_prep(), adhd_turns(), ctx)
    assert [r.status for r in out] == ["ok", "stalled", "ok"] and out[1].reason == "unavailable"


async def test_unavailable_on_every_claim_is_visible_to_the_caller(make_ctx):
    ctx = make_ctx(llm=FailingClient(LLMUnavailable("down")))
    claims = [claim("a", cid="c0.1"), claim("b", cid="c0.2")]
    out = await link_claims(claims, adhd_prep(), adhd_turns(), ctx)
    assert all(r.status == "stalled" and r.reason == "unavailable" for r in out)


async def test_to_evidence_drafts_drops_inference_and_keeps_premises(make_ctx):
    inf = {
        "items": [
            {"key": "e1", "role": "supporting", "link_type": "quote",
             "segments": [{"turn": 7, "text": "My phone, constantly."}]},
            {"key": "e2", "role": "supporting", "link_type": "quote",
             "segments": [{"turn": 9, "text": "Keys, no."}]},
            {"key": "e3", "role": "supporting", "link_type": "inference",
             "premises": ["e1", "e2"], "inference_step": "Together they show it."},
        ]
    }  # fmt: skip
    ctx = make_ctx(llm=Counting(inf))
    (r,) = await link_claims([claim("x", cid="c0.1")], adhd_prep(), adhd_turns(), ctx)
    assert [e.link_type for e in r.evidence] == ["quote", "quote", "inference"]
    drafts = to_evidence_drafts(r)
    assert [d.key for d in drafts] == ["c0.1:e1", "c0.1:e2"]
    assert all(d.segments for d in drafts)


async def test_link_output_runs_through_assemble_to_a_valid_response(make_ctx):
    atom_ctx = make_ctx(llm=FixtureClient(FIXTURES), request_id="adhd-faithful")
    section = adhd_section()
    roster = [*ROSTER, Speaker("sam1", "informant")]
    atoms = (await atomize_section(section, roster, atom_ctx, index=0)).claims
    from eval.adhd import faithful_request

    request = AuditRequest.model_validate(faithful_request())
    ctx = make_ctx(llm=FixtureClient(FIXTURES), request_id="adhd-faithful", link_mode="shortlist")
    pr = await run_prep(request.transcript, ctx)
    wanted = [atoms[0], atoms[1], atoms[10]]
    results = await link_claims(wanted, pr, request.transcript, ctx)
    assert all(r.status == "ok" and r.evidence for r in results)
    drafts = [
        ClaimDraft(
            key=c.id,
            section_index=0,
            segments=c.segments,
            span_hint=c.span_hint,
            verdict="supported",
            explanation="The respondent describes this in their own words.",
            evidence=to_evidence_drafts(r),
            ambiguous_turns=r.ambiguous_turns,
        )
        for c, r in zip(wanted, results, strict=True)
    ]
    out = assemble(request, InternalAudit(claims=drafts), ctx.settings)
    assert validate_response(out.response) == []
    claims = out.response["claims"]
    assert len(claims) == 3 and all(c["verdict"] == "supported" for c in claims)
    assert all(len(c["evidence"]) == 1 for c in claims)
    assert not out.report.drops.get("evidence_unmatched")  # every excerpt was located
    spans = [c["evidence"][0]["span"]["start"]["index"] for c in claims]
    assert spans == [3, 7, 5]
    assert not any(w["code"] == "ambiguous_speaker" for w in out.response["warnings"])


async def test_logging_is_counts_only(make_ctx, caplog):
    canaries = ["zebracanary", "wombatexcerpt", "quokkanote", "narwhalturn"]
    out = {
        "items": [
            {"key": "e1", "role": "supporting", "link_type": "quote",
             "segments": [{"turn": 7, "text": "wombatexcerpt invented"}], "note": "quokkanote"},
            {"key": "e2", "role": "supporting", "link_type": "quote",
             "segments": [{"turn": 7, "text": "My phone, constantly."}], "note": "quokkanote"},
        ]
    }  # fmt: skip
    ctx = make_ctx(llm=Counting(out))
    turns = adhd_turns()
    with caplog.at_level(logging.DEBUG, logger="iaudit"):
        await link_claims([claim("zebracanary claim", cid="c0.1")], adhd_prep(), turns, ctx)
        bad = make_ctx(llm=FailingClient(LLMUnavailable("zebracanary narwhalturn")))
        await link_claims([claim("zebracanary claim", cid="c0.2")], adhd_prep(), turns, bad)
    lines = [
        r.getMessage()
        for r in caplog.records
        if r.name == "iaudit" and r.getMessage().startswith("link_claim")
    ]
    assert len(lines) == 2
    assert 'claim_id="c0.1"' in lines[0] and "items_returned=2" in lines[0]
    assert "items_kept=1" in lines[0] and 'mode="whole"' in lines[0]
    assert 'failure="unavailable"' in lines[1]
    for c in canaries:
        assert c not in caplog.text
        assert c not in repr(ctx.metrics.records)
