"""Informational holdout-use accounting over local run metadata, read-only."""

import json
from datetime import UTC, datetime
from pathlib import Path

from iaudit_eval import paths
from iaudit_eval.scoring import PRIMARY_POLICY
from iaudit_eval.store import STORED_STATES

from .mapping import FrozenMapping


def report_extra(run: dict, runs_root: Path | None, mapping: FrozenMapping) -> dict:
    """Count valid TofuEval runs for this frozen mapping, including the saved current run.

    Creation times are compared as UTC instants with run-id ties. Bad or unrelated
    folders are ignored; inspecting a running run never acquires or creates locks.
    Dev runs are reported separately and never receive a held-out ordinal.
    """
    root = Path(runs_root) if runs_root is not None else paths.runs_dir()
    tests = []
    dev_count = 0
    for path in root.glob("*/run.json"):
        try:
            candidate = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(candidate, dict):
                continue
            if (candidate.get("dataset") != "tofueval"
                    or candidate.get("mapping_version") != mapping.mapping_version
                    or candidate.get("run_id") != path.parent.name
                    or candidate.get("state") not in STORED_STATES
                    or candidate.get("split") not in ("dev", "test", "all")):
                continue
            created = datetime.fromisoformat(candidate["created_at"])
            if created.tzinfo is None:
                continue
            if candidate["split"] == "dev":
                dev_count += 1
            else:
                tests.append((created.astimezone(UTC), candidate["run_id"]))
        except (OSError, ValueError, KeyError, TypeError):
            continue
    ordered = [run_id for _, run_id in sorted(tests)]
    ordinal = None
    if run.get("split") in ("test", "all") and run.get("run_id") in ordered:
        ordinal = ordered.index(run["run_id"]) + 1
    return {
        "mapping_version": mapping.mapping_version,
        "mapping_sha256": mapping.sha256,
        "test_run_count": len(tests),
        "test_run_ordinal": ordinal,
        "dev_run_count": dev_count,
        "label_noise_note": "TofuEval label agreement: kappa 0.34 (MediaSum), 0.42 (MeetingBank).",
        "secondary_excludes_failures": (
            "Secondary metrics exclude failed and unresolved units; primary counts them wrong."
        ),
        "primary_policy": PRIMARY_POLICY,
    }
