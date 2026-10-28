"""Atomizer prompt: a cacheable prefix (system + schema + few-shot) and a per-section user turn.

The prompt names tiers only; model ids never appear here.
"""

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from eaudit.models import Turn

from .models import AtomizerOutput

PROMPTS = Path(__file__).resolve().parents[1] / "prompts"
SYSTEM_PATH = PROMPTS / "atomize_system.md"
FEWSHOT_PATH = PROMPTS / "atomize_fewshot.json"


@dataclass(frozen=True)
class Speaker:
    speaker: str
    role: str | None = None


def roster_from_turns(turns: list[Turn]) -> list[Speaker]:
    """Distinct speakers in order. A role is kept only if every turn of that speaker gives it."""
    order: list[str] = []
    roles: dict[str, set[str | None]] = {}
    for t in turns:
        if t.speaker not in roles:
            order.append(t.speaker)
            roles[t.speaker] = set()
        roles[t.speaker].add(t.role.value if t.role else None)
    return [Speaker(s, next(iter(roles[s])) if len(roles[s]) == 1 else None) for s in order]


@lru_cache(maxsize=1)
def load_fewshot() -> list[dict]:
    return json.loads(FEWSHOT_PATH.read_text(encoding="utf-8"))["examples"]


def _roster_json(roster: list[dict] | list[Speaker]) -> str:
    rows = [{"speaker": r.speaker, "role": r.role} if isinstance(r, Speaker) else r for r in roster]
    return json.dumps(rows, ensure_ascii=False)


@lru_cache(maxsize=8)
def build_cache_prefix(max_claims: int = 30) -> str:
    schema = json.dumps(AtomizerOutput.model_json_schema(), indent=1)
    shots = []
    for n, ex in enumerate(load_fewshot(), 1):
        shots.append(
            f"## Example {n}\n"
            f"{render_user(ex['text'], ex['roster'])}\n\n"
            f"Output:\n{json.dumps(ex['output'], ensure_ascii=False, indent=1)}"
        )
    return (
        SYSTEM_PATH.read_text(encoding="utf-8")
        .replace("{max_claims}", str(max_claims))
        .replace("{schema}", schema)
        .replace("{examples}", "\n\n".join(shots))
    )


def render_user(section_text: str, roster: list[Speaker] | list[dict]) -> str:
    return f"Roster: {_roster_json(roster)}\n\nSection text:\n<<<\n{section_text}\n>>>"
