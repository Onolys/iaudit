"""R5 + R9: one mid-tier call per section (concurrent), validated, one retry on bad output."""

import asyncio
import re

from iaudit_backend.llm import LLMBadOutput, LLMError, LLMRequest, LLMTimeout
from iaudit_backend.models import Section, Turn
from iaudit_backend.safe_log import log_event
from iaudit_backend.scales import FrequencyBucket, SeverityBucket, resolve_quantity

from .models import AtomicClaim, AtomizerOutput, Quantity, SectionAtoms
from .prompt import Speaker, build_cache_prefix, render_user, roster_from_turns
from .validate import Checked, Resolved, check_output, is_trivial

_SYSTEM = "Atomize the section below. Reply with the JSON object only."
_UNSAFE = re.compile(r"[^A-Za-z0-9_-]")
_MAX_DROPPED_SHARE = 0.5


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
        r = resolve_quantity(q.kind, q.raw, scale[q.bucket] if q.bucket else None)
        out.append(
            Quantity(
                kind=q.kind,
                raw=q.raw,
                bucket=r.bucket.name if r.bucket is not None else None,
                rate_per_week=r.rate_per_week,
            )
        )
    return out


def _to_atomic(r: Resolved, section_index: int, n: int) -> AtomicClaim:
    data = r.raw.model_dump(exclude={"ref", "segments", "quantities"})
    return AtomicClaim(
        id=f"c{section_index}.{n}",
        section_index=section_index,
        segments=r.segments,
        quantities=_resolve_quantities(r.raw.quantities),
        span_hint=r.hint,
        span_quality=r.quality,
        **data,
    )


def _retry_user(user: str, out: AtomizerOutput, checked: Checked) -> str:
    """Previous output plus claim ids and error kinds only; never an echo of text."""
    problems = sorted(set(checked.errors))
    lines = "\n".join(f"- {ref}: {kind}" for ref, kind in problems)
    return (
        f"{user}\n\nPrevious output:\n{out.model_dump_json()}\n\nProblems:\n{lines}\n\n"
        "Return the full corrected JSON object."
    )


async def _call(req: LLMRequest, ctx) -> AtomizerOutput:
    return (await ctx.llm.complete_json(req, ctx.metrics)).parsed


def _score(c: Checked) -> tuple[int, int]:
    return (len(c.valid), -len(c.errors))


async def atomize_section(
    section: Section, roster: list[Speaker], ctx, *, index: int
) -> SectionAtoms:
    res = await _atomize(section, roster, ctx, index=index)
    log_event(
        "atomize_section",
        request_id=ctx.request_id,
        section_index=index,
        claims=len(res.claims),
        dropped=res.dropped,
        gaps=res.coverage_gaps,
        retries=res.retries,
        **({"failure": res.failure} if res.failure else {}),
    )
    return res


async def _atomize(section: Section, roster: list[Speaker], ctx, *, index: int) -> SectionAtoms:
    if not section.text.strip():
        return SectionAtoms(section_index=index, status="ok")
    timeout = ctx.call_timeout("atomize")
    if timeout is None:
        return SectionAtoms(section_index=index, status="failed", failure="timeout")
    cfg = ctx.settings
    key = _fixture_key(ctx.fixture_scope, index)
    req = LLMRequest(
        tier="mid",
        system=_SYSTEM,
        user=render_user(section.text, roster),
        response_model=AtomizerOutput,
        call_tag="atomize",
        unit=f"s{index}",
        cache_prefix=build_cache_prefix(cfg.atomize_max_claims),
        max_tokens=cfg.atomize_max_tokens,
        temperature=0.0,
        timeout_s=timeout,
        fixture_key=key,
        deadline=ctx.deadline,
    )
    try:
        out = await _call(req, ctx)
    except LLMError as exc:
        return SectionAtoms(section_index=index, status="failed", failure=_failure_reason(exc))
    checked = check_output(out, section.text, roster, cfg)
    retries = 0
    if checked.errors and cfg.atomize_retry and ctx.remaining() >= cfg.llm_timeout_s:
        retries = 1
        retry_req = LLMRequest(
            **{
                **req.__dict__,
                "user": _retry_user(req.user, out, checked),
                "fixture_key": f"{key}.retry" if key else None,
                "timeout_s": ctx.call_timeout("atomize") or timeout,
            }
        )
        try:
            out2 = await _call(retry_req, ctx)
        except LLMError:
            pass  # keep the first pass; invalid claims are dropped below
        else:
            checked2 = check_output(out2, section.text, roster, cfg)
            if _score(checked2) >= _score(checked):
                out, checked = out2, checked2
    return _finish(section, index, out, checked, retries)


def _finish(
    section: Section, index: int, out: AtomizerOutput, checked: Checked, retries: int
) -> SectionAtoms:
    total = len(out.claims)
    base = {
        "section_index": index,
        "dropped": checked.dropped,
        "coverage_gaps": checked.gaps,
        "retries": retries,
    }
    if not checked.valid and not is_trivial(section.text):
        return SectionAtoms(status="failed", failure="no_claims", **base)
    if total and checked.dropped / total > _MAX_DROPPED_SHARE:
        return SectionAtoms(status="failed", failure="too_many_dropped", **base)
    ids = {r.ref: f"c{index}.{n}" for n, r in enumerate(checked.valid, 1)}
    claims = [_to_atomic(r, index, n) for n, r in enumerate(checked.valid, 1)]
    links = [
        link.model_copy(
            update={
                "cause_ids": [ids[i] for i in link.cause_ids],
                "effect_id": ids[link.effect_id],
            }
        )
        for link in checked.links
    ]
    return SectionAtoms(status="ok", claims=claims, links=links, **base)


async def atomize_sections(sections: list[Section], turns: list[Turn], ctx) -> list[SectionAtoms]:
    roster = roster_from_turns(turns)
    return list(
        await asyncio.gather(
            *(atomize_section(s, roster, ctx, index=i) for i, s in enumerate(sections))
        )
    )
