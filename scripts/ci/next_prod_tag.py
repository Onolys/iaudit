#!/usr/bin/env python3
"""deploy-prod `tag` job: next prod version tag name, prod-YYYY-MM-DD.N.

N = 1 + the highest N among existing `prod-<date>.*` tags (not a count, so gaps never collide).
Usage: git ls-remote --tags origin 'prod-*' | awk '{print $2}' | next_prod_tag.py --date 2026-11-21
Reads tag names (one per line; `refs/tags/` prefix and `^{}` suffix are tolerated) from stdin, prints the next name.
Exit 0 ok, 2 bad date.
"""
import argparse
import re
import sys

DATE_RE = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$")


def next_tag(date, existing):
    if not DATE_RE.match(date):
        raise ValueError(f"date must be YYYY-MM-DD, got {date!r}")
    pat = re.compile(r"^prod-" + re.escape(date) + r"\.([0-9]+)$")
    highest = 0
    for raw in existing:
        name = raw.strip().removeprefix("refs/tags/").removesuffix("^{}")
        m = pat.match(name)
        if m:
            highest = max(highest, int(m.group(1)))
    return f"prod-{date}.{highest + 1}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", required=True, help="UTC date YYYY-MM-DD")
    args = ap.parse_args()
    try:
        print(next_tag(args.date, sys.stdin.read().splitlines()))
    except ValueError as e:
        print(e, file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
