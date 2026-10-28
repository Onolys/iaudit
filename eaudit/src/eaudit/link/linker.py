"""R3: one mid-tier call per in-scope claim."""

import asyncio
import re

from eaudit.assembler.models import EvidenceDraft
from eaudit.atomize.models import AtomicClaim
from eaudit.llm import LLMBadOutput, LLMError, LLMRequest, LLMTimeout
from eaudit.models import Turn
from eaudit.pipeline.layout import shared_layout
from eaudit.prep import PrepResult
from eaudit.safe_log import log_event

from .context import LinkContext, build_link_context
from .models import LinkerOutput, LinkResult
from .prompt import FALLBACK_SYSTEM, build_prompt, stage_system_and_block
from .validate import validate_output

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


def _retry_user(user: str, counts) -> str:
    """Error kinds and counts only; never an echo of text."""
    kinds = ("not_in_shortlist", "unlocatable", "empty_text", "item_dropped")
    lines = "\n".join(f"- {k}: {counts[k]}" for k in kinds if counts[k])
    return (
        f"{user}\n\nProblems with your previous answer (every item was rejected):\n{lines}\n\n"
        "Cite only turns shown above and copy each excerpt exactly from one turn. "
        "Return the full corrected JSON object."
    )


async def _link(claim: AtomicClaim, lctx: LinkContext, ctx) -> LinkResult:
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
    prefixes: list[str] = []
    if sl.mode == "whole" and ctx.settings.cache_layout == "shared":
        prefixes, system = shared_layout(lctx.turns, *stage_system_and_block())
        prefix = None
    elif sl.mode == "whole" and ctx.settings.link_cache_breakpoints == 2:
        # transcript and stage block cached separately (stage block moves out of `system`)
        prefixes, prefix, system = [prefix, system], None, FALLBACK_SYSTEM
    req = LLMRequest(
        tier="mid",
        system=system,
        user=user,
        response_model=LinkerOutput,
        call_tag="link",
        unit=claim.id,
        cache_prefix=prefix,
        cache_prefixes=prefixes,
        max_tokens=ctx.settings.link_max_tokens,
        temperature=0.0,
        timeout_s=timeout,
        fixture_key=_fixture_key(ctx.fixture_scope, claim.id),
        deadline=ctx.deadline,
    )

    async def call(r: LLMRequest) -> LinkerOutput:
        async with lctx.sem:
            return (await ctx.llm.complete_json(r, ctx.metrics)).parsed

    cfg = ctx.settings
    try:
        out = await call(req)
    except LLMError as exc:
        res.status, res.reason = "stalled", _stall_reason(exc)
        return res
    v = validate_output(claim.id, out, lctx.turns, lctx.prep, sl.indices, cfg)
    all_dropped = bool(out.items) and v.counts["items_kept"] == 0
    if all_dropped and cfg.link_retry and ctx.remaining() >= cfg.llm_timeout_s:
        res.counts["retries"] = 1
        retry = LLMRequest(
            **{
                **req.__dict__,
                "user": _retry_user(user, v.counts),
                "fixture_key": f"{req.fixture_key}.retry" if req.fixture_key else None,
                "timeout_s": ctx.call_timeout("link") or timeout,
            }
        )
        try:
            out = await call(retry)
        except LLMError as exc:
            res.status, res.reason = "stalled", _stall_reason(exc)
            return res
        v = validate_output(claim.id, out, lctx.turns, lctx.prep, sl.indices, cfg)
        all_dropped = bool(out.items) and v.counts["items_kept"] == 0
    for k, n in v.counts.items():
        res.counts[k] = res.counts.get(k, 0) + n
    if all_dropped:
        res.status, res.reason = "stalled", "all_dropped"
        return res
    res.evidence, res.ambiguous_turns = v.evidence, v.ambiguous_turns
    return res


async def link_one(claim: AtomicClaim, lctx: LinkContext, ctx) -> LinkResult:
    """Link one claim. Never raises for per-claim failures; logs counts only."""
    res = await _link(claim, lctx, ctx)
    if claim.scope == "in_scope":
        c = res.counts
        dropped = sum(
            c.get(k, 0)
            for k in ("not_in_shortlist", "unlocatable", "empty_text", "item_dropped", "dup_key")
        )
        log_event(
            "link_claim",
            request_id=ctx.request_id,
            claim_id=claim.id,
            mode=res.mode,
            shortlist_size=len(res.shortlist),
            items_returned=c.get("items_returned", 0),
            items_kept=c.get("items_kept", 0),
            dropped=dropped,
            coerced=c.get("coerced", 0),
            retries=c.get("retries", 0),
            **({"failure": res.reason} if res.status == "stalled" else {}),
        )
    return res


def to_evidence_drafts(r: LinkResult) -> list[EvidenceDraft]:
    """Drafts for 02. Inference items stay internal; their premises are ordinary items."""
    return [e.draft for e in r.evidence if e.link_type != "inference"]


async def link_claims(claims: list[AtomicClaim], prep: PrepResult, turns: list[Turn], ctx):
    """Gather wrapper over build_link_context + link_one."""
    lctx = build_link_context(turns, prep, ctx)
    return list(await asyncio.gather(*(link_one(c, lctx, ctx) for c in claims)))
