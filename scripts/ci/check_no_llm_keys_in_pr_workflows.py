#!/usr/bin/env python3
"""Fail if a PR-triggered workflow references secret LLM/STT keys.

PR CI must never read provider keys (live tests run only nightly/manual).
Scans .github/workflows/*.yml(yaml) whose `on:` includes pull_request or
pull_request_target, plus local reusable workflows they call. Comments ignored.

Usage: check_no_llm_keys_in_pr_workflows.py [ROOT]   (default: repo root)
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

PROVIDERS = r"(?:ANTHROPIC|GEMINI|OPENAI|LITELLM|CLAUDE|DEEPGRAM|ASSEMBLYAI|ELEVENLABS|SPEECH|STT|LLM)"
# Provider-named env var / secret (e.g. ANTHROPIC_API_KEY, DEEPGRAM_TOKEN, STT_KEY), or Google API key.
FORBIDDEN = re.compile(
    rf"\b(?:{PROVIDERS}_[A-Z0-9_]*(?:KEY|TOKEN|SECRET|CREDENTIALS?)|GOOGLE_API_KEY)\b"
)
PR_TRIGGER = re.compile(r"\bpull_request(?:_target)?\b")
USES_LOCAL = re.compile(r"uses:\s*['\"]?\./(\.github/workflows/[\w.\-]+\.ya?ml)")


def _code_lines(text: str) -> list[tuple[int, str]]:
    out = []
    for n, line in enumerate(text.splitlines(), 1):
        stripped = line.split(" #", 1)[0] if not line.lstrip().startswith("#") else ""
        if stripped.strip():
            out.append((n, stripped))
    return out


def _on_block(lines: list[tuple[int, str]]) -> str:
    block: list[str] = []
    inside = False
    for _, line in lines:
        if re.match(r"""^["']?on["']?\s*:""", line):
            inside = True
            block.append(line)
        elif inside and re.match(r"^\S", line):
            break
        elif inside:
            block.append(line)
    return "\n".join(block)


def violations(root: Path) -> list[str]:
    wf_dir = root / ".github" / "workflows"
    files = sorted([*wf_dir.glob("*.yml"), *wf_dir.glob("*.yaml")]) if wf_dir.is_dir() else []
    parsed = {f.relative_to(root).as_posix(): _code_lines(f.read_text(encoding="utf-8")) for f in files}
    scoped = {rel for rel, lines in parsed.items() if PR_TRIGGER.search(_on_block(lines))}
    for rel in list(scoped):  # reusable workflows called from PR workflows
        for _, line in parsed[rel]:
            m = USES_LOCAL.search(line)
            if m and m.group(1) in parsed:
                scoped.add(m.group(1))
    bad = []
    for rel in sorted(scoped):
        for n, line in parsed[rel]:
            for m in FORBIDDEN.finditer(line):
                bad.append(f"{rel}:{n}: {m.group(0)}")
    return bad


def main(argv: list[str]) -> int:
    root = Path(argv[1]) if len(argv) > 1 else Path(__file__).resolve().parents[2]
    bad = violations(root)
    for b in bad:
        print("LLM/STT KEY IN PR WORKFLOW", b)
    print(f"{len(bad)} LLM/STT key reference(s) in PR-triggered workflows")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
