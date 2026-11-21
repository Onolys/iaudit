"""Contract: in a workflow job, no actions/checkout step may follow a google-github-actions/auth step.

checkout cleans the workspace and deletes the gha-creds-*.json file that auth wrote there.
"""
from pathlib import Path

import yaml

WORKFLOWS = Path(__file__).resolve().parents[2] / ".github" / "workflows"


def _violations():
    found = []
    for wf in sorted(WORKFLOWS.glob("*.yml")):
        jobs = (yaml.safe_load(wf.read_text()) or {}).get("jobs") or {}
        for name, job in jobs.items():
            authed = False
            for step in job.get("steps") or []:
                uses = step.get("uses", "")
                if uses.startswith("google-github-actions/auth"):
                    authed = True
                elif uses.startswith("actions/checkout") and authed:
                    found.append(f"{wf.name}:{name}")
    return found


def test_no_checkout_after_gcp_auth():
    assert _violations() == []


if __name__ == "__main__":
    test_no_checkout_after_gcp_auth()
    print("ok   no actions/checkout after google-github-actions/auth")
