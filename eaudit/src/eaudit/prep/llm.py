"""R3 (optional): cheap-tier act tagging for turns the rules left unsure.

Only unsure turns are sent, in chunks; an invalid or failed chunk keeps the rule result
(`act_source="rule_fallback"`) and bumps `degraded_chunks`. Prep never fails a request.
"""

import asyncio
import re
from dataclasses import replace

from pydantic import BaseModel, ConfigDict

from eaudit.llm import LLMError, LLMRequest
from eaudit.safe_log import log_event

from .models import Act, IndexedTurn
from .prompt import SYSTEM, render_user

_UNSAFE = re.compile(r"[^A-Za-z0-9_-]")


class PrepActItem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    index: int
    acts: list[Act]


class PrepActsOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    items: list[PrepActItem]


def _chunks(indices: list[int], size: int) -> list[list[int]]:
    size = max(1, size)
    return [indices[i : i + size] for i in range(0, len(indices), size)]


async def _tag_chunk(
    n: int,
    requested: list[int],
    turns: list[IndexedTurn],
    kinds: dict[int, frozenset[Act]],
    ctx,
) -> dict[int, frozenset[Act]] | None:
    """The tagged acts per requested index, or None when the chunk is unusable."""
    cfg = ctx.settings
    timeout = ctx.call_timeout("prep")
    if timeout is None:
        return None
    lo = max(0, requested[0] - cfg.prep_context_turns)
    hi = min(len(turns), requested[-1] + cfg.prep_context_turns + 1)
    scope = _UNSAFE.sub("_", ctx.fixture_scope) if ctx.fixture_scope else None
    req = LLMRequest(
        tier="cheap",
        system=SYSTEM,
        user=render_user(turns[lo:hi], requested, kinds),
        response_model=PrepActsOutput,
        call_tag="prep_acts",
        unit=f"p{n}",
        max_tokens=600,
        temperature=0.0,
        timeout_s=timeout,
        fixture_key=f"{scope}.prep.p{n}" if scope else None,
        deadline=ctx.deadline,
    )
    try:
        out = (await ctx.llm.complete_json(req, ctx.metrics)).parsed
    except LLMError:
        return None
    got = {item.index: frozenset(item.acts) for item in out.items}
    if len(got) != len(out.items) or not set(got) <= set(requested):
        return None
    return got


async def tag_unsure(
    turns: list[IndexedTurn], kinds: dict[int, frozenset[Act]], ctx
) -> tuple[list[IndexedTurn], int]:
    """Merge LLM acts into turns. Returns (turns, degraded_chunks)."""
    if not kinds:
        return turns, 0
    chunks = _chunks(sorted(kinds), ctx.settings.prep_chunk_turns)
    results = await asyncio.gather(
        *(_tag_chunk(n, c, turns, kinds, ctx) for n, c in enumerate(chunks))
    )
    out = list(turns)
    degraded = 0
    for chunk, got in zip(chunks, results, strict=True):
        if got is None:
            degraded += 1
            for i in chunk:
                out[i] = replace(out[i], act_source="rule_fallback")
            continue
        for i in chunk:
            t = out[i]
            decided = {a for a in t.acts if a not in kinds[i]}  # rule-decided kinds stay
            decided |= {a for a in got.get(i, frozenset()) if a in kinds[i]}
            out[i] = replace(t, acts=frozenset(decided), act_source="llm")
    log_event("prep_llm", request_id=ctx.request_id, chunks=len(chunks), degraded_chunks=degraded)
    return out, degraded
