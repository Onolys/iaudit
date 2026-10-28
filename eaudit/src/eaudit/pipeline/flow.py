"""Per-section and per-claim flows. Each writes its result into RunState as it completes."""

import asyncio

from eaudit.assembler.models import ClaimDraft
from eaudit.atomize import atomize_section
from eaudit.atomize.models import AtomicClaim
from eaudit.check import check_one, passthrough_oos
from eaudit.link import build_link_context, link_one
from eaudit.models import AuditRequest, Section
from eaudit.prep import prep, prep_rules_only

from .state import RunState
from .warmup import wait_warm


async def prep_flow(st: RunState, req: AuditRequest, ctx) -> None:
    try:
        with st.span("prep"):
            try:
                st.prep = await asyncio.wait_for(
                    prep(req.transcript, ctx), ctx.settings.prep_soft_timeout_s
                )
            except TimeoutError:  # prep must never stall the claims waiting on it
                st.prep = prep_rules_only(req.transcript)
    finally:
        st.prep_ready.set()  # waiters never hang, even if prep failed or was cancelled


async def section_flow(
    st: RunState, req: AuditRequest, roster, index: int, section: Section, ctx
) -> None:
    with st.span("atomize"):
        atoms = await atomize_section(section, roster, ctx, index=index)
    st.write_atoms(index, atoms)
    if atoms.status != "ok":
        return
    for claim in atoms.claims:
        if len(st.admitted) >= ctx.settings.pipeline_max_claims:
            st.truncated = True
            continue
        st.admitted[claim.id] = claim
        if claim.scope != "in_scope":
            st.write_draft(claim.id, passthrough_oos(claim))
            continue
        # registered before this flow exits, so the run is never "idle" in between
        st.spawn(lambda c=claim: claim_flow(st, req, c, ctx), claim_id=claim.id)


async def claim_flow(st: RunState, req: AuditRequest, claim: AtomicClaim, ctx) -> None:
    await st.prep_ready.wait()  # an event, never `await prep_task`
    if st.prep is None:
        raise RuntimeError("prep did not complete")
    if st.link_ctx is None:  # no await between check and set: built exactly once
        st.link_ctx = build_link_context(req.transcript, st.prep, ctx)
    await wait_warm(st, ctx.settings.warmup_max_wait_s)
    with st.span("link"):
        link = await link_one(claim, st.link_ctx, ctx)
    with st.span("check"):
        draft: ClaimDraft = await check_one(claim, link, st.prep, st.prep.turns, ctx)
    st.write_draft(claim.id, draft)
