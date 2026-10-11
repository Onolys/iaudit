"""FullPipeline: prep || atomize, then per-claim link -> check, then assemble."""

import asyncio
import dataclasses
import time

from iaudit_backend.assembler import InternalAudit, SectionFailure, assemble
from iaudit_backend.atomize import roster_from_turns
from iaudit_backend.check import stalled_draft
from iaudit_backend.models import AuditRequest, AuditResponse

from .flow import prep_flow, section_flow
from .state import RunState


def _section_reason(failure: str | None) -> str:
    return "timeout" if failure in ("timeout", "deadline") else "error"


class FullPipeline:
    async def run(self, req: AuditRequest, ctx) -> AuditResponse:
        cfg = ctx.settings
        llm_deadline = ctx.deadline - cfg.assemble_reserve_s
        sctx = dataclasses.replace(ctx, deadline=llm_deadline)  # stages see the LLM deadline
        st = RunState()
        try:
            roster = roster_from_turns(req.transcript)
            st.spawn(lambda: prep_flow(st, req, sctx))
            for i, section in enumerate(req.assessment):
                st.spawn(
                    lambda i=i, s=section: section_flow(st, req, roster, i, s, sctx), section=i
                )
            try:
                await asyncio.wait_for(st.idle.wait(), max(0.0, llm_deadline - time.monotonic()))
            except TimeoutError:
                st.deadline_hit = True
                await st.cancel_all(cfg.cancel_grace_s)
        finally:
            for t in list(st.tasks):  # outer cancellation: never leak tasks
                t.cancel()
        internal = self._collect(st, len(req.assessment), ctx)
        outcome = await asyncio.to_thread(assemble, req, internal, cfg)
        return AuditResponse.model_validate(outcome.response)

    @staticmethod
    def _collect(st: RunState, n_sections: int, ctx) -> InternalAudit:
        """Read results after the cancel wait; fill what never finished by the locked rules."""
        stalls = ctx.extras.setdefault("check_stalls", {})
        failures: list[SectionFailure] = []
        for i in range(n_sections):
            atoms = st.atoms.get(i)
            if atoms is None:
                reason = "error" if i in st.errored_sections else "timeout"  # never finished
                failures.append(SectionFailure(section_index=i, reason=reason))
            elif atoms.status != "ok":
                failures.append(
                    SectionFailure(section_index=i, reason=_section_reason(atoms.failure))
                )
        claims = []
        for cid, claim in st.admitted.items():
            draft = st.drafts.get(cid)
            if draft is None:  # unfinished at the deadline, or its flow raised
                reason = "error" if cid in st.errored_claims else "deadline"
                stalls.setdefault(cid, reason)
                draft = stalled_draft(claim, reason)
            claims.append(draft)
        return InternalAudit(claims=claims, section_failures=failures, truncated=st.truncated)
