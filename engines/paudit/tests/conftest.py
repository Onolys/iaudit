"""Minimal in-test pack (generic ids, nothing protocol-specific) until a real pack ships."""

import copy
import json
from pathlib import Path

import pytest
import yaml

PACK_YAML = {
    "pack_format": "0.0.1",
    "id": "demo",
    "version": "1.0.0",
    "source": {"citation": "Synthetic test pack", "url": "https://example.invalid", "permission_note": "n/a"},
    "speaker_roles": {"subject": "clinician", "other": "client"},
    "items": [
        {
            "id": "g1", "kind": "global", "label": "Global one", "definition": "d",
            "scale": {"min": 1, "max": 5, "default": 3}, "evidence_min": 2,
            "caps": [{"max": 3, "when": "poor_practice_cited", "source": "manual p. 1"}],
        },
        {"id": "g2", "kind": "global", "label": "Global two", "definition": "d",
         "scale": {"min": 1, "max": 5, "default": 3}, "evidence_min": 1},
        {"id": "a", "kind": "count", "label": "A", "definition": "d", "examples": ["x"]},
        {"id": "b", "kind": "count", "label": "B", "definition": "d"},
        {"id": "c", "kind": "count", "label": "C", "definition": "d"},
    ],
    "params": {"volleys_per_call": 10, "code_max_tokens": 4000, "globals_max_tokens": 2000},
    "rules": [
        {"kind": "one_code_per_utterance"},
        {"kind": "max_per_unit", "unit": "volley", "code": "any", "n": 1},
        {"kind": "exclusive_group", "unit": "volley", "codes": ["b", "c"], "precedence": ["c", "b"]},
    ],
    "volley": {"breaks_on": "other_speaker", "min_other_words": 0},
    "summaries": [
        {"id": "s1", "label": "Mean", "expr": "(a+b)/2", "format": "number",
         "reference": {"fair": 1.0, "good": 2.0, "direction": "higher_better"}},
    ],
    "input_checks": [
        {"id": "dur_max", "kind": "duration_max", "value": 25, "severity": "error"},
        {"id": "goal", "kind": "param_required", "value": "change_goal", "severity": "error"},
    ],
    "compare": {"g1": {"kind": "within", "tolerance": 1}, "a": {"kind": "count_diff", "tolerance": 2}},
    "evaluation": {"anything": ["goes", {"here": 1}]},
}

RATING_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "properties": {
        "globals": {"type": "object", "properties": {"g1": {}, "g2": {}}},
        "counts": {"type": "object", "properties": {"a": {}, "b": {}, "c": {}}},
    },
}

REPORT_YAML = {"sections": [{"id": "overview", "label": "Overview", "items": ["g1", "a", "s1"]}]}

PROMPTS = {
    "code_system.md": "code system",
    "code_fewshot.json": "[]",
    "globals_system.md": "globals system",
    "globals_fewshot.json": "[]",
}


def write_pack(root: Path, pack=None, rating=None, report=None, prompts=None, rules_py="# hooks\n"):
    root.mkdir(parents=True, exist_ok=True)
    (root / "pack.yaml").write_text(yaml.safe_dump(pack if pack is not None else PACK_YAML, sort_keys=False))
    (root / "rating.schema.json").write_text(json.dumps(rating if rating is not None else RATING_SCHEMA))
    (root / "report.yaml").write_text(yaml.safe_dump(report if report is not None else REPORT_YAML))
    (root / "prompts").mkdir(exist_ok=True)
    for name, body in (prompts if prompts is not None else PROMPTS).items():
        (root / "prompts" / name).write_text(body)
    if rules_py is not None:
        (root / "rules.py").write_text(rules_py)
    return root


@pytest.fixture
def pack_data():
    return copy.deepcopy(PACK_YAML)


@pytest.fixture
def rating():
    return copy.deepcopy(RATING_SCHEMA)


@pytest.fixture
def protocols(tmp_path):
    """A protocols/ dir holding demo-1.0.0."""
    write_pack(tmp_path / "protocols" / "demo-1.0.0")
    return tmp_path / "protocols"
