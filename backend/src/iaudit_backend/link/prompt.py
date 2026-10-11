"""Linker prompt. Layout: [cache_prefix: system (+ transcript in whole mode)] ... claim block last.

Names tiers only; no model ids. Turn text is never altered or escaped (excerpts stay verbatim).
"""

import json
from functools import lru_cache
from pathlib import Path

from iaudit_backend.atomize.models import AtomicClaim
from iaudit_backend.models import Turn
from iaudit_backend.prep import PrepResult

from .models import LinkerOutput

PROMPTS = Path(__file__).resolve().parents[1] / "prompts"
SYSTEM_PATH = PROMPTS / "link_system.md"
FEWSHOT_PATH = PROMPTS / "link_fewshot.json"
_FALLBACK_SYSTEM = "Return the JSON object only."


@lru_cache(maxsize=1)
def load_fewshot() -> list[dict]:
    return json.loads(FEWSHOT_PATH.read_text(encoding="utf-8"))["examples"]


def _turn_line(i: int, speaker: str, role: str | None, text: str) -> str:
    return f'<turn i="{i}" speaker="{speaker}" role="{role or "unknown"}">{text}</turn>'


def _gap(a: int, b: int) -> str:
    return f"[... turns {a}-{b} omitted ...]" if a != b else f"[... turn {a} omitted ...]"


def _render(rows: list[tuple[int, str, str | None, str]], total: int | None) -> str:
    """rows are (index, speaker, role, text) sorted by index; gaps get an omitted marker."""
    out: list[str] = []
    prev = -1
    for i, sp, role, text in rows:
        if i > prev + 1 and (prev >= 0 or total is not None):
            out.append(_gap(prev + 1, i - 1))
        out.append(_turn_line(i, sp, role, text))
        prev = i
    if total is not None and rows and prev < total - 1:
        out.append(_gap(prev + 1, total - 1))
    return "\n".join(out)


def render_turns(turns: list[Turn], indices: list[int]) -> str:
    """Deterministic, act-free rendering (byte-identical across claims for the same selection)."""
    rows = [(i, turns[i].speaker, turns[i].role.value if turns[i].role else None, turns[i].text)
            for i in sorted(indices)]  # fmt: skip
    return _render(rows, len(turns))


def _claim_lines(
    proposition: str,
    reported_by: list[str],
    polarity: str,
    timeframe: str,
    quantities: list[str],
    hints: str,
) -> str:
    lines = [
        f"Claim: {proposition}",
        f"Reported by: {', '.join(reported_by) or 'unspecified'}",
        f"Polarity: {polarity}",
        f"Timeframe: {timeframe}",
        f"Quantities: {'; '.join(quantities) if quantities else 'none'}",
    ]
    if hints:
        lines.append(f"Heuristic dialogue-act hints (may be wrong): {hints}")
    return "\n".join(lines)


def act_hints(prep: PrepResult, indices: list[int]) -> str:
    parts = []
    for i in sorted(indices):
        acts = sorted(a.value for a in prep.turns[i].acts)
        if acts:
            parts.append(f"{i}={'+'.join(acts)}")
    return ", ".join(parts)


def render_claim_block(claim: AtomicClaim, prep: PrepResult, indices: list[int]) -> str:
    who = [f"{r.source}:{r.speaker}" if r.speaker else r.source for r in claim.reported_by]
    return _claim_lines(
        claim.proposition,
        who,
        claim.polarity,
        claim.timeframe,
        [q.raw for q in claim.quantities],
        act_hints(prep, indices),
    )


@lru_cache(maxsize=1)
def stage_block() -> str:
    shots = []
    for n, ex in enumerate(load_fewshot(), 1):
        c = ex["claim"]
        rows = [(t["i"], t["speaker"], t["role"], t["text"]) for t in ex["turns"]]
        shots.append(
            f"## Example {n}\n"
            + _claim_lines(
                c["proposition"],
                c["reported_by"],
                c["polarity"],
                c["timeframe"],
                c["quantities"],
                "",
            )
            + "\n\nTurns:\n"
            + _render(rows, None)
            + "\n\nOutput:\n"
            + json.dumps(ex["output"], ensure_ascii=False, indent=1)
        )
    schema = json.dumps(LinkerOutput.model_json_schema(), indent=1)
    return f"# Output schema\n\n{schema}\n\n# Examples\n\n" + "\n\n".join(shots)


def common_system() -> str:
    return SYSTEM_PATH.read_text(encoding="utf-8")


def build_prompt(
    claim: AtomicClaim, turns: list[Turn], prep: PrepResult, indices: list[int], mode: str
) -> tuple[str, str, str]:
    """Return (cache_prefix, system, user). Only the claim block varies between claims."""
    block = render_claim_block(claim, prep, indices)
    if mode == "whole":
        prefix = (
            f"{common_system()}\n\n# Transcript\n\n{render_turns(turns, list(range(len(turns))))}"
        )
        user = f"{block}\n\nCite turns from the transcript above."
        return prefix, stage_block(), user
    prefix = f"{common_system()}\n\n{stage_block()}"
    user = f"{block}\n\nTurns you may cite:\n{render_turns(turns, indices)}"
    return prefix, _FALLBACK_SYSTEM, user
