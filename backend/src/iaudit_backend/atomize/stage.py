"""R5: one mid-tier call per section; all sections run concurrently."""

import asyncio
import re

from iaudit_backend.llm import LLMBadOutput, LLMError, LLMRequest, LLMTimeout
from iaudit_backend.models import Section, Turn
from iaudit_backend.scales import FrequencyBucket, SeverityBucket, resolve_quantity

from .models import AtomicClaim, AtomizerOutput, Quantity, RawClaim, SectionAtoms
from .prompt import Speaker, build_cache_prefix, render_user, roster_from_turns

_SYSTEM = "Atomize the section below. Reply with the JSON object only."
_UNSAFE = re.compile(r"[^A-Za-z0-9_-]")


def _fixture_key(scope: str | None, index: int) -> str | None:
    if not scope:
        return None
    return f"{_UNSAFE.sub('_', scope)}.atomize.s{index}"


def _failure_reason(exc: LLMError) -> str:
    if isinstance(exc, LLMTimeout):
        return "timeout"
    if isinstance(exc, LLMBadOutput):
        return "bad_output"
    return "unavailable"


def _resolve_quantities(quantities: list[Quantity]) -> list[Quantity]:
    out = []
    for q in quantities:
        scale = FrequencyBucket if q.kind == "frequency" else SeverityBucket
        llm_bucket = scale[q.bucket] if q.bucket else None
        r = resolve_quantity(q.kind, q.raw, llm_bucket)
        out.append(
            Quantity(
                kind=q.kind,
                raw=q.raw,
                bucket=r.bucket.name if r.bucket is not None else None,
                rate_per_week=r.rate_per_week if r.rate_per_week is not None else None,
            )
        )
    return out


def to_atomic(raw: RawClaim, section_index: int, n: int) -> AtomicClaim:
    data = raw.model_dump(exclude={"ref"})
    data["quantities"] = [q.model_dump() for q in _resolve_quantities(raw.quantities)]
    return AtomicClaim(id=f"c{section_index}.{n}", section_index=section_index, **data)


async def atomize_section(
    section: Section, roster: list[Speaker], ctx, *, index: int
) -> SectionAtoms:
    timeout = ctx.call_timeout("atomize")
    if timeout is None:
        return SectionAtoms(section_index=index, status="failed", failure="timeout")
    req = LLMRequest(
        tier="mid",
        system=_SYSTEM,
        user=render_user(section.text, roster),
        response_model=AtomizerOutput,
        call_tag="atomize",
        cache_prefix=build_cache_prefix(ctx.settings.atomize_max_claims),
        max_tokens=ctx.settings.atomize_max_tokens,
        temperature=0.0,
        timeout_s=timeout,
        fixture_key=_fixture_key(ctx.fixture_scope, index),
        deadline=ctx.deadline,
    )
    try:
        result = await ctx.llm.complete_json(req, ctx.metrics)
    except LLMError as exc:
        return SectionAtoms(section_index=index, status="failed", failure=_failure_reason(exc))
    out: AtomizerOutput = result.parsed
    claims = [to_atomic(c, index, n) for n, c in enumerate(out.claims, 1)]
    ids = {c.ref: f"c{index}.{n}" for n, c in enumerate(out.claims, 1)}
    links = [
        link.model_copy(
            update={
                "cause_ids": [ids.get(r, r) for r in link.cause_ids],
                "effect_id": ids.get(link.effect_id, link.effect_id),
            }
        )
        for link in out.links
    ]
    return SectionAtoms(section_index=index, status="ok", claims=claims, links=links)


async def atomize_sections(sections: list[Section], turns: list[Turn], ctx) -> list[SectionAtoms]:
    roster = roster_from_turns(turns)
    return list(
        await asyncio.gather(
            *(atomize_section(s, roster, ctx, index=i) for i, s in enumerate(sections))
        )
    )
