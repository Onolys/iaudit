#!/usr/bin/env python3
"""Fail on broken relative markdown links (tracked .md files, excluding historical agent_files).

Usage: check_links.py [ROOT]   (default: repo root)
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

LINK = re.compile(r"(?<!!)\[[^\]]*\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")
FENCE = re.compile(r"^\s*(```|~~~)")
SKIP_PREFIX = ("http://", "https://", "mailto:", "#", "tel:")


def md_files(root: Path) -> list[Path]:
    try:
        out = subprocess.run(
            ["git", "ls-files", "--cached", "--others", "--exclude-standard", "*.md"],
            cwd=root, capture_output=True, text=True, check=True,
        ).stdout.split()
        names = out
    except (subprocess.CalledProcessError, FileNotFoundError):
        names = [str(p.relative_to(root)) for p in root.rglob("*.md")]
    return [
        root / n
        for n in names
        if "docs/agent_files/" not in n and "node_modules/" not in n and (root / n).is_file()
    ]


def broken_links(root: Path) -> list[str]:
    bad: list[str] = []
    for md in md_files(root):
        in_fence = False
        for lineno, line in enumerate(md.read_text(encoding="utf-8").splitlines(), 1):
            if FENCE.match(line):
                in_fence = not in_fence
                continue
            if in_fence:
                continue
            for target in LINK.findall(line):
                if target.startswith(SKIP_PREFIX):
                    continue
                path = target.split("#", 1)[0].split("?", 1)[0]
                if path and not (md.parent / path).exists():
                    bad.append(f"{md.relative_to(root)}:{lineno}: {target}")
    return bad


def main(argv: list[str]) -> int:
    root = Path(argv[1]) if len(argv) > 1 else Path(__file__).resolve().parents[2]
    bad = broken_links(root)
    for b in bad:
        print("BROKEN", b)
    print(f"{len(bad)} broken relative link(s)")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
