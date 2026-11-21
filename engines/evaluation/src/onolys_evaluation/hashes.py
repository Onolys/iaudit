"""Prompt hashes for the evaluation run's `run_info` (SP03 R7/D13): the pack's tips prompt files
(by file name) and the engine-owned templates (`engine:*`), so a template change shows even when
the pack is unchanged. Text never enters `run_info`, only hashes."""

import hashlib

from onolys_core.run_info import hash_files
from paudit.pack import Pack

from onolys_evaluation import tips
from onolys_evaluation.compare import template_strings


def _sha(*parts: str) -> str:
    h = hashlib.sha256()
    for p in parts:
        h.update(p.encode("utf-8"))
        h.update(b"\0")
    return h.hexdigest()[:16]


def evaluation_prompt_hashes(pack: Pack) -> dict[str, str]:
    return {
        tips.PROMPT_FILE: hash_files([pack.root / "prompts" / tips.PROMPT_FILE]),
        "engine:tips_output_format": _sha(tips._OUTPUT_FORMAT),
        "engine:compare_templates": _sha(*template_strings()),
    }
