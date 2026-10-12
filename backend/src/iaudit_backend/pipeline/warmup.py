"""Cache warm-up at t=0 (live mode, whole mode, large transcripts only).

While atomize runs (5-10 s), tiny calls write the prompt prefixes link and check will use, so the
first real calls already hit the cache. Failures and slow warm-ups are ignored: flows wait at
most `warmup_max_wait_s` for `warm_ready`.
"""

import asyncio

from pydantic import BaseModel

from iaudit_backend.check import verifier
from iaudit_backend.link import prompt as link_prompt
from iaudit_backend.link.context import choose_mode, estimate_tokens
from iaudit_backend.llm import LLMError, LLMRequest
from iaudit_backend.models import AuditRequest
from iaudit_backend.safe_log import log_event

from .layout import stage_text, transcript_prefix
from .state import RunState


class WarmupOut(BaseModel):
    ok: bool = True


def warmup_enabled(req: AuditRequest, cfg) -> bool:
    """Live mode, shared layout, and a transcript big enough to be cacheable."""
    if not cfg.cache_warmup or cfg.llm_mode != "live" or cfg.cache_layout != "shared":
        return False
    return estimate_tokens(req.transcript) >= cfg.cache_min_prefix_tokens


def _tiny(ctx, **prefix_fields) -> LLMRequest:
    return LLMRequest(
        tier="mid",
        system="Reply with the JSON object only.",
        user="ok",
        response_model=WarmupOut,
        call_tag="warmup",
        max_tokens=1,
        temperature=0.0,
        timeout_s=ctx.call_timeout("link"),
        deadline=ctx.deadline,
        retry=False,
        **prefix_fields,
    )


async def _call(ctx, req: LLMRequest) -> None:
    if req.timeout_s is None:  # no budget left for even a tiny call
        return
    try:
        await ctx.llm.complete_json(req, ctx.metrics)
    except LLMError:
        pass  # warm-up is best effort


async def warmup_flow(st: RunState, req: AuditRequest, ctx) -> None:
    try:
        cfg = ctx.settings
        link_stage = stage_text(*link_prompt.stage_system_and_block())
        check_stage = stage_text(verifier.common_system(), verifier.stage_block())
        if choose_mode(estimate_tokens(req.transcript), cfg) == "whole":
            p1 = transcript_prefix(req.transcript)
            await _call(ctx, _tiny(ctx, cache_prefixes=[p1]))
            await asyncio.gather(
                _call(ctx, _tiny(ctx, cache_prefixes=[p1, link_stage])),
                _call(ctx, _tiny(ctx, cache_prefixes=[p1, check_stage])),
            )
        else:  # shortlist mode: no transcript prefix, just the two stage blocks
            link_only = stage_text(link_prompt.common_system(), link_prompt.stage_block())
            check_only = stage_text(verifier.common_system(), verifier.stage_block())
            await asyncio.gather(
                _call(ctx, _tiny(ctx, cache_prefix=link_only)),
                _call(ctx, _tiny(ctx, cache_prefix=check_only)),
            )
        log_event("warmup", request_id=ctx.request_id, calls=3)
    except asyncio.CancelledError:
        raise
    except Exception as exc:  # best effort: record the class only
        log_event("warmup_error", request_id=ctx.request_id, exc_class=type(exc).__name__)
    finally:
        st.warm_ready.set()


async def wait_warm(st: RunState, max_wait_s: float) -> None:
    if st.warm_ready.is_set():
        return
    try:
        await asyncio.wait_for(st.warm_ready.wait(), max_wait_s)
    except TimeoutError:
        pass
