"""R6: three thin adapters (gold, linked, e2e) plus the oracle used to prove the harness.

Every mode ends the same way: drafts -> the assembler -> a contract response, so scoring only
ever sees the contract response and assembler behaviour is part of every measurement.
"""

import asyncio
import json
import time

from eaudit.assembler import InternalAudit, assemble
from eaudit.assembler.models import (
    ClaimDraft,
    ConcernDraft,
    EvidenceDraft,
    ExcerptSegment,
)
from eaudit.check import check_one
from eaudit.config import Settings
from eaudit.link import build_link_context, link_one
from eaudit.link.models import LinkedEvidence, LinkResult
from eaudit.link.validate import answer_status
from eaudit.llm import FixtureMiss, MetricsCollector
from eaudit.models import AuditRequest, EvidenceRole, Verdict
from eaudit.pipeline import RequestContext
from eaudit.pipeline.full import FullPipeline
from eaudit.prep import prep
from eval.adhd import DATA
from eval.gold import GoldClaim, load_gold

MODES = ("oracle", "gold", "linked", "e2e")


class MissCounter:
    """Wraps a client and counts FixtureMiss, so a replay gap is an error, never a score."""

    def __init__(self, inner) -> None:
        self.inner = inner
        self.misses = 0

    async def complete_json(self, req, metrics=None):
        try:
            return await self.inner.complete_json(req, metrics)
        except FixtureMiss:
            self.misses += 1
            raise


def load_fixture(name: str, root=DATA) -> tuple[dict, list[GoldClaim]]:
    request = json.loads((root / "requests" / f"{name}.json").read_text(encoding="utf-8"))
    return request, load_gold(name, root)


def make_ctx(request: dict, settings: Settings, llm) -> RequestContext:
    return RequestContext(
        settings=settings,
        llm=llm,
        metrics=MetricsCollector(),
        request_id=request["request_id"],
        deadline=time.monotonic() + settings.audit_deadline_s,
    )


# -- oracle: echoes the gold -----------------------------------------------------------------


def _evidence_drafts(g: GoldClaim, request: dict, claim_key: str) -> list[EvidenceDraft]:
    """Gold evidence as drafts. Adjacent turns with the same role form one cross-turn item."""
    runs: list[list] = []
    for e in sorted(g.evidence, key=lambda e: e.turn):
        if runs and runs[-1][-1].turn + 1 == e.turn and runs[-1][-1].role == e.role:
            runs[-1].append(e)
        else:
            runs.append([e])
    turns = request["transcript"]
    return [
        EvidenceDraft(
            key=f"{claim_key}:e{n}",
            role=EvidenceRole(run[0].role),
            segments=[ExcerptSegment(turn_index=e.turn, text=turns[e.turn]["text"]) for e in run],
        )
        for n, run in enumerate(runs, 1)
    ]


def oracle_audit(request: dict, gold: list[GoldClaim]) -> InternalAudit:
    claims = []
    for n, g in enumerate(gold, 1):
        key = f"c{g.section_index}.{n}"
        evidence = _evidence_drafts(g, request, key)
        keys = [e.key for e in evidence]
        words = " ".join(g.explanation_contains)
        ambiguous = sorted(
            {
                s.turn_index
                for e in evidence
                for s in e.segments
                if "role" not in request["transcript"][s.turn_index]
            }
        )
        claims.append(
            ClaimDraft(
                key=key,
                section_index=g.section_index,
                segments=[g.claim_text],
                span_hint=(g.start, g.end),
                verdict=Verdict(g.verdict),
                explanation=f"Oracle echo of the gold label. {words}".strip(),
                concerns=[
                    ConcernDraft(
                        type=c,
                        explanation=f"Oracle echo: {c.replace('_', ' ')}.",
                        evidence_keys=keys,
                    )
                    for c in g.concerns_required
                ],  # fmt: skip
                evidence=evidence,
                ambiguous_turns=ambiguous if "ambiguous_speaker" in g.expect_warnings else [],
            )
        )
    return InternalAudit(claims=claims)


async def run_oracle(request: dict, gold: list[GoldClaim], settings: Settings, llm=None):
    audit = oracle_audit(request, gold)
    model = AuditRequest.model_validate(request)
    return assemble(model, audit, settings).response, MetricsCollector()


# -- gold / linked / e2e ---------------------------------------------------------------------


def gold_link(g: GoldClaim, claim, request: dict, prep_result) -> LinkResult:
    """The gold evidence as a LinkResult, so Gold mode runs the checker alone."""
    drafts = _evidence_drafts(g, request, claim.id)
    items = [
        LinkedEvidence(
            draft=d,
            link_type="quote",
            answer_status=answer_status([s.turn_index for s in d.segments], prep_result),
        )
        for d in drafts
    ]
    turns = prep_result.turns
    amb = sorted(
        {s.turn_index for d in drafts for s in d.segments if turns[s.turn_index].role is None}
    )
    return LinkResult(
        claim_id=claim.id, mode="whole", shortlist=list(range(len(prep_result.turns))),
        evidence=items, ambiguous_turns=amb,
    )  # fmt: skip


async def run_gold(request: dict, gold: list[GoldClaim], settings: Settings, llm):
    ctx = make_ctx(request, settings, llm)
    model = AuditRequest.model_validate(request)
    pr = await prep(model.transcript, ctx)
    claims = [g.atomic_claim(n) for n, g in enumerate(gold, 1)]
    drafts = await asyncio.gather(
        *(
            check_one(c, gold_link(g, c, request, pr), pr, pr.turns, ctx)
            for g, c in zip(gold, claims, strict=True)
        )
    )
    return assemble(model, InternalAudit(claims=list(drafts)), settings).response, ctx.metrics


async def run_linked(request: dict, gold: list[GoldClaim], settings: Settings, llm):
    ctx = make_ctx(request, settings, llm)
    model = AuditRequest.model_validate(request)
    pr = await prep(model.transcript, ctx)
    claims = [g.atomic_claim(n) for n, g in enumerate(gold, 1)]
    lctx = build_link_context(model.transcript, pr, ctx)

    async def one(c):
        link = await link_one(c, lctx, ctx)
        return await check_one(c, link, pr, pr.turns, ctx)

    drafts = await asyncio.gather(*(one(c) for c in claims))
    return assemble(model, InternalAudit(claims=list(drafts)), settings).response, ctx.metrics


async def run_e2e(request: dict, gold: list[GoldClaim], settings: Settings, llm):
    ctx = make_ctx(request, settings, llm)
    resp = await FullPipeline().run(AuditRequest.model_validate(request), ctx)
    return resp.to_json(), ctx.metrics


RUNNERS = {"oracle": run_oracle, "gold": run_gold, "linked": run_linked, "e2e": run_e2e}
