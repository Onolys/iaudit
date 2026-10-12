"""R3: one mid-tier verifier call per claim that needs one. The LLM observes; code decides.

Layout: [cache_prefix: check system (+ transcript in whole mode)] ... claim block and evidence
items last. Names tiers only; turn text is never altered.
"""

import asyncio
import json
import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from iaudit_backend.atomize.models import AtomicClaim
from iaudit_backend.config import Settings
from iaudit_backend.link.models import LinkResult
from iaudit_backend.link.prompt import render_claim_block, render_turns
from iaudit_backend.llm import LLMBadOutput, LLMError, LLMRequest, LLMTimeout
from iaudit_backend.pipeline.layout import shared_layout
from iaudit_backend.prep import IndexedTurn, PrepResult

from .models import VerifierOutput

PROMPTS = Path(__file__).resolve().parents[1] / "prompts"
_FALLBACK_SYSTEM = "Return the JSON object only."
_UNSAFE = re.compile(r"[^A-Za-z0-9_-]")
_ID_UNSAFE = re.compile(r"[^A-Za-z0-9_.-]|\.\.")


@lru_cache(maxsize=1)
def load_fewshot() -> list[dict]:
    return json.loads((PROMPTS / "check_fewshot.json").read_text(encoding="utf-8"))["examples"]


def _claim_lines(c: dict) -> str:
    return "\n".join(
        [
            f"Claim: {c['proposition']}",
            f"Reported by: {', '.join(c['reported_by']) or 'unspecified'}",
            f"Polarity: {c['polarity']}",
            f"Timeframe: {c['timeframe']} (stated in the text: "
            f"{'yes' if c['timeframe_explicit'] else 'no'})",
            f"Hedged: {'yes' if c['hedged'] else 'no'}",
            f"Quantities: {'; '.join(c['quantities']) if c['quantities'] else 'none'}",
        ]
    )


def _item_line(e: dict) -> str:
    if e.get("inference"):
        return f'- key={e["key"]} inference premises={",".join(e["premises"])} step="{e["step"]}"'
    turns = ",".join(str(i) for i in e["turns"])
    return (
        f"- key={e['key']} turns={turns} linker_role={e['linker_role']} "
        f'answer_status={e["answer_status"]} text="{e["text"]}"'
    )


@lru_cache(maxsize=1)
def stage_block() -> str:
    shots = []
    for n, ex in enumerate(load_fewshot(), 1):
        rows = [
            f'<turn i="{t["i"]}" speaker="{t["speaker"]}" role="{t["role"] or "unknown"}">'
            f"{t['text']}</turn>"
            for t in ex["turns"]
        ]
        shots.append(
            f"## Example {n}\n{_claim_lines(ex['claim'])}\n\nTurns:\n"
            + "\n".join(rows)
            + "\n\nEvidence items:\n"
            + "\n".join(_item_line(e) for e in ex["evidence"])
            + "\n\nOutput:\n"
            + json.dumps(ex["output"], ensure_ascii=False, indent=1)
        )
    schema = json.dumps(VerifierOutput.model_json_schema(), indent=1)
    return f"# Output schema\n\n{schema}\n\n# Examples\n\n" + "\n\n".join(shots)


def common_system() -> str:
    return (PROMPTS / "check_system.md").read_text(encoding="utf-8")


def _evidence_lines(link: LinkResult) -> str:
    rows = []
    for ev in link.evidence:
        if ev.link_type == "inference":
            rows.append(
                _item_line(
                    {
                        "key": ev.draft.key,
                        "inference": True,
                        "premises": ev.premise_keys,
                        "step": ev.inference_step or "",
                    }
                )
            )
        else:
            rows.append(
                _item_line(
                    {
                        "key": ev.draft.key,
                        "turns": [s.turn_index for s in ev.draft.segments],
                        "linker_role": ev.draft.role.value,
                        "answer_status": ev.answer_status,
                        "text": " / ".join(s.text for s in ev.draft.segments),
                    }
                )
            )
    return "\n".join(rows)


def build_prompt(
    claim: AtomicClaim, link: LinkResult, prep: PrepResult, turns: list[IndexedTurn]
) -> tuple[str, str, str]:
    """Return (cache_prefix, system, user). Only the claim block and evidence vary per claim."""
    indices = list(range(len(turns))) if link.mode == "whole" else sorted(link.shortlist)
    block = render_claim_block(claim, prep, indices)
    block += f"\nHedged: {'yes' if claim.hedged else 'no'}"
    block += f"\nTimeframe stated in the text: {'yes' if claim.timeframe_explicit else 'no'}"
    user = f"{block}\n\nEvidence items to judge:\n{_evidence_lines(link)}"
    if link.mode == "whole":
        prefix = f"{common_system()}\n\n# Transcript\n\n{render_turns(turns, indices)}"
        return prefix, stage_block(), f"{user}\n\nThe transcript is above."
    prefix = f"{common_system()}\n\n{stage_block()}"
    return prefix, _FALLBACK_SYSTEM, f"{user}\n\nTurns shown:\n{render_turns(turns, indices)}"


def expected_keys(link: LinkResult) -> tuple[list[str], list[str]]:
    """(item keys that must be judged, inference keys)."""
    plain = [e.draft.key for e in link.evidence if e.link_type != "inference"]
    inf = [e.draft.key for e in link.evidence if e.link_type == "inference"]
    return plain, inf


def clean_output(out: VerifierOutput, link: LinkResult) -> tuple[VerifierOutput, list[str]]:
    """Drop unknown keys. Returns the cleaned output and the item keys still unjudged."""
    plain, inf = expected_keys(link)
    known = set(plain) | set(inf)
    seen: set[str] = set()
    items = []
    for i in out.items:
        if i.key in plain and i.key not in seen:
            seen.add(i.key)
            items.append(i)
    flags = []
    for f in out.flags:
        keys = [k for k in f.keys if k in known]
        flags.append(f.model_copy(update={"keys": keys}))
    infs, seen_inf = [], set()
    for g in out.inferences:
        if g.key in inf and g.key not in seen_inf:
            seen_inf.add(g.key)
            infs.append(g)
    cleaned = out.model_copy(update={"items": items, "flags": flags, "inferences": infs})
    missing = [k for k in plain if k not in seen] + [k for k in inf if k not in seen_inf]
    return cleaned, missing


def apply_floors(out: VerifierOutput, cfg: Settings) -> tuple[VerifierOutput, dict[str, int]]:
    """Fixed confidence floors. Below the floor an observation is dropped and counted."""
    counts: dict[str, int] = {}
    vals = cfg.check_conf_values

    def drop(name: str) -> None:
        counts[name] = counts.get(name, 0) + 1

    items = []
    for i in out.items:
        if vals[i.conf] >= cfg.check_min_conf_p0:
            items.append(i)
        else:
            drop("items_below_floor")
    flags = []
    for f in out.flags:
        counts["flags_seen"] = counts.get("flags_seen", 0) + 1
        if vals[f.conf] >= cfg.check_min_conf_p1:
            flags.append(f)
        else:
            drop("flags_below_floor")
    infs = []
    for g in out.inferences:
        if vals[g.conf] >= cfg.check_min_conf_p0:
            infs.append(g)
        else:
            drop("inferences_below_floor")
    return out.model_copy(update={"items": items, "flags": flags, "inferences": infs}), counts


@dataclass
class VerifierResult:
    output: VerifierOutput | None = None  # cleaned, floors not yet applied
    stall: str | None = None  # timeout | unavailable | bad_output
    unjudged: list[str] = field(default_factory=list)
    retries: int = 0
    calls: int = 0


def _stall_reason(exc: LLMError) -> str:
    if isinstance(exc, LLMTimeout):
        return "timeout"
    if isinstance(exc, LLMBadOutput):
        return "bad_output"
    return "unavailable"


def _fixture_key(scope: str | None, claim_id: str) -> str | None:
    if not scope:
        return None
    return f"{_UNSAFE.sub('_', scope)}.check.{_ID_UNSAFE.sub('_', claim_id)}"


def _semaphore(ctx) -> asyncio.Semaphore:
    sem = ctx.extras.get("check_sem")
    if sem is None:
        sem = ctx.extras["check_sem"] = asyncio.Semaphore(ctx.settings.check_concurrency)
    return sem


def _retry_user(user: str, missing: list[str]) -> str:
    keys = ", ".join(missing)
    return (
        f"{user}\n\nYour previous answer did not judge these evidence keys: {keys}.\n"
        "Return the full corrected JSON object with every evidence item judged."
    )


async def verify(
    claim: AtomicClaim, link: LinkResult, prep: PrepResult, turns: list[IndexedTurn], ctx
) -> VerifierResult:
    """Call the verifier; one semantic retry when items are unjudged. Never raises LLMError."""
    res = VerifierResult()
    cfg = ctx.settings
    timeout = ctx.call_timeout("check")
    if timeout is None:
        res.stall = "timeout"
        return res
    prefix, system, user = build_prompt(claim, link, prep, turns)
    prefixes: list[str] = []
    if link.mode == "whole" and cfg.cache_layout == "shared":
        prefixes, system = shared_layout(turns, common_system(), stage_block())
        prefix = None
    req = LLMRequest(
        tier="mid",
        system=system,
        user=user,
        response_model=VerifierOutput,
        call_tag="check",
        unit=claim.id,
        cache_prefix=prefix,
        cache_prefixes=prefixes,
        max_tokens=cfg.check_max_tokens,
        temperature=0.0,
        timeout_s=timeout,
        fixture_key=_fixture_key(ctx.fixture_scope, claim.id),
        deadline=ctx.deadline,
    )

    async def call(r: LLMRequest) -> VerifierOutput:
        async with _semaphore(ctx):
            res.calls += 1
            return (await ctx.llm.complete_json(r, ctx.metrics)).parsed

    try:
        out = await call(req)
    except LLMError as exc:
        res.stall = _stall_reason(exc)
        return res
    out, missing = clean_output(out, link)
    if missing and cfg.check_retry and ctx.remaining() >= cfg.llm_timeout_s:
        res.retries = 1
        retry = LLMRequest(
            **{
                **req.__dict__,
                "user": _retry_user(user, missing),
                "fixture_key": f"{req.fixture_key}.retry" if req.fixture_key else None,
                "timeout_s": ctx.call_timeout("check") or timeout,
            }
        )
        try:
            out = await call(retry)
        except LLMError as exc:
            res.stall = _stall_reason(exc)
            return res
        out, missing = clean_output(out, link)
    if missing:
        res.stall, res.unjudged = "bad_output", missing
        return res
    res.output = out
    return res
