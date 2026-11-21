#!/usr/bin/env python3
"""Fork-safety guard for workflows.

`workflow_run.branches` matches the head branch NAME, so a fork PR from a branch called `main` would pass it.
Every entry job (no `needs`) of a workflow triggered by `workflow_run` must therefore gate its workflow_run path
on event == 'push', same-repo head and head_branch == 'main'. `pull_request_target` is banned (runs with secrets
on fork-controlled input). Run: python3 scripts/ci/test_workflow_run_guard.py
"""
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
REQUIRED = [
    "github.event.workflow_run.event == 'push'",
    "github.event.workflow_run.head_repository.full_name == github.repository",
    "github.event.workflow_run.head_branch == 'main'",
    "github.event.workflow_run.conclusion == 'success'",
]


def triggers(doc):
    on = doc.get("on", doc.get(True))  # PyYAML parses bare `on` as True
    if isinstance(on, str):
        return {on}
    return set(on or [])


def violations(root=ROOT):
    out = []
    for f in sorted((root / ".github" / "workflows").glob("*.yml")):
        doc = yaml.safe_load(f.read_text())
        trig = triggers(doc)
        if "pull_request_target" in trig:
            out.append(f"{f.name}: pull_request_target is not allowed")
        if "workflow_run" not in trig:
            continue
        for name, job in (doc.get("jobs") or {}).items():
            if job.get("needs"):
                continue
            cond = str(job.get("if", ""))
            for req in REQUIRED:
                if req not in cond:
                    out.append(f"{f.name}: job {name} `if` lacks `{req}`")
    return out


if __name__ == "__main__":
    v = violations()
    for line in v:
        print("FAIL", line)
    print("FAIL" if v else "ok   workflow_run jobs are fork-safe")
    sys.exit(1 if v else 0)
