"""R3: one mid-tier call per in-scope claim."""

import re

from iaudit_backend.assembler.models import EvidenceDraft, ExcerptSegment
from iaudit_backend.atomize.models import AtomicClaim
from iaudit_backend.llm import LLMBadOutput, LLMError, LLMRequest, LLMTimeout

from .context import LinkContext
from .models import LinkedEvidence, LinkerOutput, LinkResult
from .prompt import build_prompt

_UNSAFE = re.compile(r"[^A-Za-z0-9_-]")
_ID_UNSAFE = re.compile(r"[^A-Za-z0-9_.-]|\.\.")  # claim ids are code-made: c0.1


def _fixture_key(scope: str | None, claim_id: str) -> str | None:
    if not scope:
        return None
    return f"{_UNSAFE.sub('_', scope)}.link.{_ID_UNSAFE.sub('_', claim_id)}"


def _stall_reason(exc: LLMError) -> str:
    if isinstance(exc, LLMTimeout):
        return "timeout"
    if isinstance(exc, LLMBadOutput):
        return "bad_output"
    return "unavailable"


def _basic_evidence(claim: AtomicClaim, out: LinkerOutput) -> list[LinkedEvidence]:
    """Unvalidated conversion (validation arrives in the next step of the pipeline)."""
    ev = []
    for n, it in enumerate(out.items, 1):
        if it.link_type == "inference" or not it.segments:
            continue
        segs = [ExcerptSegment(turn_index=s.turn, text=s.text) for s in it.segments]
        draft = EvidenceDraft(key=f"{claim.id}:e{n}", role=it.role, segments=segs, note=it.note)
        ev.append(LinkedEvidence(draft=draft, link_type=it.link_type))
    return ev


async def link_one(claim: AtomicClaim, lctx: LinkContext, ctx) -> LinkResult:
    if claim.scope != "in_scope":
        return LinkResult(claim_id=claim.id, mode=lctx.mode)
    sl = lctx.select(claim)
    res = LinkResult(claim_id=claim.id, mode=sl.mode, shortlist=list(sl.indices))
    if sl.mode == "empty":
        return res  # searched, found nothing (counted by the caller)
    timeout = ctx.call_timeout("link")
    if timeout is None:
        res.status, res.reason = "stalled", "timeout"
        return res
    prefix, system, user = build_prompt(claim, lctx.turns, lctx.prep, sl.indices, sl.mode)
    req = LLMRequest(
        tier="mid",
        system=system,
        user=user,
        response_model=LinkerOutput,
        call_tag="link",
        cache_prefix=prefix,
        max_tokens=ctx.settings.link_max_tokens,
        temperature=0.0,
        timeout_s=timeout,
        fixture_key=_fixture_key(ctx.fixture_scope, claim.id),
        deadline=ctx.deadline,
    )
    try:
        async with lctx.sem:
            out: LinkerOutput = (await ctx.llm.complete_json(req, ctx.metrics)).parsed
    except LLMError as exc:
        res.status, res.reason = "stalled", _stall_reason(exc)
        return res
    res.evidence = _basic_evidence(claim, out)
    return res
