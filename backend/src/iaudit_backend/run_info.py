"""Run provenance for the response: configured model ids and prompt hashes.

Hashes use the same algorithm as eval/run.py::prompt_hashes (the recording manifest), so the
values are comparable. Carries no text; tokens and cost are never populated here.
"""

import hashlib
from functools import cache
from pathlib import Path

from iaudit_backend.config import Settings

PROMPTS = Path(__file__).resolve().parent / "prompts"
STAGE_FILES = {
    "atomize": ["atomize_system.md", "atomize_fewshot.json"],
    "link": ["link_system.md", "link_fewshot.json"],
    "check": ["check_system.md", "check_fewshot.json"],
}


def compute_hashes(prompts_dir: Path) -> dict[str, str]:
    out = {}
    for stage, files in STAGE_FILES.items():
        h = hashlib.sha256()
        for f in files:
            h.update((prompts_dir / f).read_bytes())
        out[stage] = h.hexdigest()[:16]
    from iaudit_backend.prep.prompt import SYSTEM

    out["prep"] = hashlib.sha256(SYSTEM.encode()).hexdigest()[:16]
    return out


@cache
def _cached() -> tuple[tuple[str, str], ...]:
    return tuple(compute_hashes(PROMPTS).items())


def prompt_hashes() -> dict[str, str]:
    """Computed once per process."""
    return dict(_cached())


def build(settings: Settings) -> dict:
    return {
        "models": {
            "cheap": settings.model_cheap,
            "mid": settings.model_mid,
            "strong": settings.model_strong,
        },
        "prompt_hashes": prompt_hashes(),
    }
