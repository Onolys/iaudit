"""FullPipeline: prep || atomize, then per-claim link -> check, then assemble."""

import asyncio
import dataclasses
import time

from eaudit.assembler import InternalAudit, SectionFailure, assemble
from eaudit.atomize import roster_from_turns
from eaudit.check import stalled_draft
from eaudit.models import AuditRequest, AuditResponse

from .flow import prep_flow, section_flow
from .guards import assess
from .metrics import log_audit_done, pipeline_snapshot, summarize
from .state import RunState
from .warmup import warmup_enabled, warmup_flow


def _section_reason(failure: str | None) -> str:
    return "timeout" if failure in ("timeout", "deadline") else "error"


class FullPipeline:
    async def run(self, req: AuditRequest, ctx) -> AuditResponse:
        cfg = ctx.settings
        llm_deadline = ctx.deadline - cfg.assemble_reserve_s
        sctx = dataclasses.replace(ctx, deadline=llm_deadline)  # stages see the LLM deadline
        t0 = time.monotonic()
        st = RunState()
        ctx.extras["run_state"] = st
        try:
            roster = roster_from_turns(req.transcript)
            st.spawn(lambda: prep_flow(st, req, sctx))
            if warmup_enabled(req, cfg):
                st.warm_ready.clear()
                # untracked on purpose: a slow warm-up must never hold the run open
                st.warm_task = asyncio.create_task(warmup_flow(st, req, sctx))
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
            if st.warm_task is not None:
                st.warm_task.cancel()
        internal = self._collect(st, len(req.assessment), ctx)
        a0 = time.monotonic()
        try:
            self._guard(st, req, internal, ctx)
        except Exception:  # 503 / 504 / 500: the run still leaves its numbers behind
            self._record(st, internal, ctx, t0, a0, a0, llm_deadline)
            raise
        outcome = await asyncio.to_thread(assemble, req, internal, cfg)
        self._record(st, internal, ctx, t0, a0, time.monotonic(), llm_deadline)
        return AuditResponse.model_validate(outcome.response)

    @staticmethod
    def _record(st, internal, ctx, t0: float, a0: float, now: float, llm_deadline: float) -> None:
        summary = summarize(st, internal, round((now - a0) * 1000), round((now - t0) * 1000))
        ctx.extras["pipeline_metrics"] = summary
        ctx.metrics.set_pipeline(
            *pipeline_snapshot(st, summary, t0, llm_deadline, a0, ctx.deadline)
        )
        log_audit_done(ctx, summary)

    @staticmethod
    def _guard(st: RunState, req: AuditRequest, internal: InternalAudit, ctx) -> None:
        by_key = {d.key: d for d in internal.claims}
        in_scope = [c for c in st.admitted.values() if c.scope == "in_scope"]
        reasons = {a.failure for a in st.atoms.values() if a.failure}
        reasons |= set(ctx.extras.get("check_stalls", {}).values())
        if st.errors:
            reasons.add("error")
        err = assess(
            sections_total=len(req.assessment),
            sections_ok=sum(1 for a in st.atoms.values() if a.status == "ok"),
            in_scope=len(in_scope),
            in_scope_ok=sum(1 for c in in_scope if by_key[c.id].outcome == "ok"),
            reasons=reasons,
        )
        if err is not None:
            raise err

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
