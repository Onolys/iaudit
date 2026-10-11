"""Stage 3 entry points. The verifier observes; code decides (see synth.py)."""

import asyncio

from iaudit_backend.assembler.models import ClaimDraft, ConcernDraft, Outcome
from iaudit_backend.atomize.models import AtomicClaim
from iaudit_backend.config import Settings
from iaudit_backend.link.models import LinkResult
from iaudit_backend.models import ConcernType, EvidenceRole, Verdict
from iaudit_backend.prep import IndexedTurn, PrepResult
from iaudit_backend.safe_log import log_event

from .group_a import GroupA, run_group_a
from .models import Concern, Decision, JudgedEvidence
from .synth import decide, judge
from .templates import STALLED_TEXT, Slots, claim_text, concern_text, source_noun, vet_revision
from .verifier import apply_floors, verify


def _base(claim: AtomicClaim, **fields) -> ClaimDraft:
    return ClaimDraft(
        key=claim.id,
        section_index=claim.section_index,
        segments=list(claim.segments),
        span_hint=claim.span_hint,
        **fields,
    )


def stalled_draft(claim: AtomicClaim, reason: str) -> ClaimDraft:
    """A claim that could not be checked; 06 uses it for deadline and exception stalls too."""
    del reason  # the draft carries no reason text; check_one records it in ctx.extras
    return _base(
        claim,
        outcome=Outcome.stalled,
        verdict=Verdict.insufficient_evidence,
        explanation=STALLED_TEXT,
    )


def passthrough_oos(claim: AtomicClaim) -> ClaimDraft:
    """Out-of-scope claims are not checked; 03's fixed sentence is the reason."""
    return _base(
        claim,
        verdict=Verdict.out_of_scope,
        explanation=claim_text(Verdict.out_of_scope, []),
        out_of_scope_reason=claim.oos_reason,
    )


def _slots(keys: list[str], judged: list[JudgedEvidence], turns: list[IndexedTurn]) -> Slots:
    by_key = {it.key: it for it in judged}
    idx = sorted({i for k in keys if k in by_key for i in by_key[k].turns})
    roles = [turns[i].role for i in idx if turns[i].role != "interviewer"]
    return Slots(source_noun(roles), len(idx))


def _draft(
    claim: AtomicClaim,
    link: LinkResult,
    ga: GroupA,
    judged: list[JudgedEvidence],
    dec: Decision,
    revision: str | None,
    turns: list[IndexedTurn],
    cfg: Settings,
) -> ClaimDraft:
    evidence = [
        it.linked.draft.model_copy(update={"role": dec.roles[it.key]})
        for it in judged
        if it.key in dec.roles
    ]
    concerns = [
        ConcernDraft(
            type=c.type,
            explanation=concern_text(c, _slots(c.keys or list(dec.roles), judged, turns)),
            evidence_keys=list(c.keys),
        )
        for c in dec.concerns
    ]
    return _base(
        claim,
        verdict=dec.verdict,
        explanation=claim_text(dec.verdict, dec.concerns),
        suggested_revision=vet_revision(revision, dec.verdict, dec.concerns, cfg),
        concerns=concerns,
        evidence=evidence,
        ambiguous_turns=ga.ambiguous,
    )


def _no_call_draft(
    claim: AtomicClaim, link: LinkResult, ga: GroupA, turns: list[IndexedTurn], cfg: Settings
) -> ClaimDraft:
    """D3 / D7: every item is a question or non-answer, so no verifier call is made."""
    items = [e for e in link.evidence if e.link_type != "inference"]
    judged = [
        JudgedEvidence(
            key=e.draft.key,
            linked=e,
            turns=[s.turn_index for s in e.draft.segments if 0 <= s.turn_index < len(turns)],
            endorsed=False,
        )
        for e in items
    ]
    ctype = (
        ConcernType.question_as_answer if ga.question_as_answer else ConcernType.unsupported_claim
    )
    dec = Decision(
        Verdict.insufficient_evidence,
        [Concern(ctype, list(ga.question_as_answer))],
        {it.key: EvidenceRole.qualifying for it in judged},
        "D3" if ga.question_as_answer else "D7",
    )
    return _draft(claim, link, ga, judged, dec, None, turns, cfg)


def _no_evidence_draft(claim: AtomicClaim, link: LinkResult, cfg: Settings) -> ClaimDraft:
    dec = Decision(
        Verdict.insufficient_evidence, [Concern(ConcernType.unsupported_claim)], row="D2"
    )
    ga = GroupA(ambiguous=sorted(set(link.ambiguous_turns)))
    return _draft(claim, link, ga, [], dec, None, [], cfg)


def _stall(claim: AtomicClaim, reason: str, ctx) -> ClaimDraft:
    ctx.extras.setdefault("check_stalls", {})[claim.id] = reason
    return stalled_draft(claim, reason)


async def _check(
    claim: AtomicClaim, link: LinkResult, prep: PrepResult, turns: list[IndexedTurn], ctx
) -> tuple[ClaimDraft, dict[str, int]]:
    cfg = ctx.settings
    ga = run_group_a(claim, link, turns)
    counts: dict[str, int] = {"role_skipped": ga.role_skipped, "called": 0}
    if ga.no_call:
        return _no_call_draft(claim, link, ga, turns, cfg), counts
    res = await verify(claim, link, prep, turns, ctx)
    counts["called"] = res.calls
    counts["retries"] = res.retries
    if res.stall is not None:
        counts["failure"] = res.stall
        return _stall(claim, res.stall, ctx), counts
    vout, floor_counts = apply_floors(res.output, cfg)
    judged, sig = judge(claim, link, ga, turns, vout, floor_counts)
    dec = decide(claim, judged, sig, cfg)
    for k, n in {**sig.counts, **dec.counts}.items():
        counts[k] = counts.get(k, 0) + n
    counts["verdict"] = dec.verdict.value
    return _draft(claim, link, ga, judged, dec, vout.suggested_revision, turns, cfg), counts


async def check_one(
    claim: AtomicClaim,
    link: LinkResult | None,
    prep: PrepResult,
    turns: list[IndexedTurn],
    ctx,
) -> ClaimDraft:
    """Check one claim. Never raises for per-claim failures; logs counts only."""
    if claim.scope != "in_scope":
        return passthrough_oos(claim)
    if link is None:
        return _stall(claim, "unavailable", ctx)
    if link.status == "stalled":
        return _stall(claim, link.reason or "unavailable", ctx)
    if not link.evidence:
        return _no_evidence_draft(claim, link, ctx.settings)
    try:
        draft, counts = await _check(claim, link, prep, turns, ctx)
    except Exception as exc:  # a bug in one claim must not take down the others
        log_event(
            "check_claim", claim_id=claim.id, failure="bad_output", exc_class=type(exc).__name__
        )
        return _stall(claim, "bad_output", ctx)
    log_event("check_claim", claim_id=claim.id, **counts)
    return draft


async def check_claims(
    claims: list[AtomicClaim],
    links: list[LinkResult],
    prep: PrepResult,
    turns: list[IndexedTurn],
    ctx,
) -> list[ClaimDraft]:
    """One draft per claim, in input order."""
    by_id = {r.claim_id: r for r in links}
    return list(
        await asyncio.gather(*(check_one(c, by_id.get(c.id), prep, turns, ctx) for c in claims))
    )


__all__ = ["check_claims", "check_one", "passthrough_oos", "stalled_draft"]
