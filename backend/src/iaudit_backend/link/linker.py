"""R3: one mid-tier call per in-scope claim."""

import re

from iaudit_backend.atomize.models import AtomicClaim
from iaudit_backend.llm import LLMBadOutput, LLMError, LLMRequest, LLMTimeout

from .context import LinkContext
from .models import LinkerOutput, LinkResult
from .prompt import build_prompt
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
