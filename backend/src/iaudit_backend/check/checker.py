"""Stage 3 entry points. The verifier observes; code decides (see synth.py)."""

import asyncio

from iaudit_backend.assembler.models import ClaimDraft, ConcernDraft, Outcome
from iaudit_backend.atomize.models import AtomicClaim
from iaudit_backend.link.models import LinkResult
from iaudit_backend.models import ConcernType, Verdict
from iaudit_backend.prep import IndexedTurn, PrepResult

STALLED_TEXT = "This claim could not be checked in this run."
NO_EVIDENCE_TEXT = (
    "This claim is not substantiated by the supplied interview: no supporting evidence was found."
)
NO_EVIDENCE_CONCERN = "No evidence in the supplied interview was found for this claim."


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
    del reason  # counts-only logging happens at the call site; the draft carries no reason text
    return _base(
        claim, outcome=Outcome.stalled, verdict=Verdict.insufficient_evidence,
        explanation=STALLED_TEXT,
    )  # fmt: skip


def passthrough_oos(claim: AtomicClaim) -> ClaimDraft:
    """Out-of-scope claims are not checked; 03's fixed sentence is the reason."""
    return _base(
        claim,
        verdict=Verdict.out_of_scope,
        explanation="This statement is outside what the audit checks.",
        out_of_scope_reason=claim.oos_reason,
    )


def no_evidence_draft(claim: AtomicClaim, ambiguous: list[int]) -> ClaimDraft:
    return _base(
        claim,
        verdict=Verdict.insufficient_evidence,
        explanation=NO_EVIDENCE_TEXT,
        concerns=[
            ConcernDraft(type=ConcernType.unsupported_claim, explanation=NO_EVIDENCE_CONCERN)
        ],
        ambiguous_turns=sorted(set(ambiguous)),
    )


async def check_one(
    claim: AtomicClaim,
    link: LinkResult | None,
    prep: PrepResult,
    turns: list[IndexedTurn],
    ctx,
) -> ClaimDraft:
    """Check one claim. Never raises for per-claim failures."""
    if claim.scope != "in_scope":
        return passthrough_oos(claim)
    if link is None:
        return stalled_draft(claim, "unavailable")
    if link.status == "stalled":
        return stalled_draft(claim, link.reason or "unavailable")
    if not link.evidence:
        return no_evidence_draft(claim, link.ambiguous_turns)
    return stalled_draft(claim, "unavailable")  # filled in by the group A / verifier tasks


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
