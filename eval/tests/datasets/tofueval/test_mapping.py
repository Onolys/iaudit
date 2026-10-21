"""The frozen mapping rejects drift without rejecting future predictions."""

import importlib.util
import json
import re
import sys
from copy import deepcopy
from dataclasses import replace
from hashlib import sha256
from pathlib import Path

import pytest

from iaudit_eval import contracts

ROOT = Path(__file__).resolve().parents[4]
MODULE = ROOT / "eval/datasets/tofueval/mapping.py"
MAPPING = MODULE.with_suffix(".json")
V1_SHA256 = "0b5ecb4b33e56d6b3252ef349eaca0158fbc964924d5e0871e1a8266ebad77af"


def loader():
    assert MODULE.is_file(), "TofuEval frozen mapping loader is not implemented"
    spec = importlib.util.spec_from_file_location("fictional_tofueval_mapping", MODULE)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_frozen_bytes_match_approved_brief_and_version_pin():
    assert MAPPING.is_file(), "Frozen mapping v1.0.0 is not implemented"
    brief = (ROOT / "docs/agent_files/eval-tofueval-20261020/brainstorming.md").read_text()
    approved = re.search(r"### 5\.7.*?```json\n(.*?)```", brief, re.S)[1].encode()
    assert MAPPING.read_bytes() == approved
    assert sha256(MAPPING.read_bytes()).hexdigest() == V1_SHA256
    mapping = loader().load_mapping()
    assert mapping.mapping_version == "1.0.0"
    assert mapping.sha256 == V1_SHA256


@pytest.mark.parametrize(
    ("error_type", "dataset", "allowed"),
    [
        ("Extrinsic Information", "mediasum", {"unsupported_claim"}),
        ("Mis-Referencing", "mediasum", {"wrong_attribution"}),
        ("Mis-Referencing", "meetingbank", None),
        ("Tense/Modality", "meetingbank", {"timeframe_mismatch", "certainty_inflation"}),
        ("Tense/Modality Error", "mediasum", {"timeframe_mismatch", "certainty_inflation"}),
        ("Stating Opinion as Fact", "mediasum", {"certainty_inflation", "wrong_attribution"}),
        ("Stating Opinion as Fact", "meetingbank", {"certainty_inflation"}),
        ("Contradiction", "meetingbank", {"contradictory_evidence", "negation_reversal"}),
        ("Nuanced Meaning Shift", "mediasum", None),
        ("Reasoning Error", "meetingbank", None),
    ],
)
def test_applicable_allowed_honours_dataset_and_recall_only(error_type, dataset, allowed):
    mapping = loader().load_mapping()
    assert mapping.applicable_allowed(error_type, dataset) == allowed


def test_unknown_predicted_concerns_are_ignored_for_matching():
    module = loader()
    mapping = module.load_mapping()
    assert not mapping.matches("Extrinsic Information", "mediasum", ["quantity_mismatch"])
    assert mapping.matches("Extrinsic Information", "mediasum", ["quantity_mismatch", "unsupported_claim"])
    assert not mapping.matches("Stating Opinion as Fact", "meetingbank", ["wrong_attribution"])
    assert not mapping.matches("Mis-Referencing", "meetingbank", ["wrong_attribution"])
    assert not mapping.matches("Reasoning Error", "mediasum", ["unsupported_causal_link"])
    assert mapping.mapped_concerns == {
        "unsupported_claim", "wrong_attribution", "timeframe_mismatch", "certainty_inflation",
        "contradictory_evidence", "negation_reversal",
    }
    assert module.matches("Tense/Modality Error", "mediasum", ["timeframe_mismatch"])
    assert module.applicable_allowed("Mis-Referencing", "meetingbank") is None
    assert module.normalize_type("Tense/Modality Error") == "Tense/Modality"
    assert module.normalize_type("Unknown Type") == "Unknown Type"


@pytest.mark.parametrize("concern", ["unsupported_claim", "wrong_attribution", "timeframe_mismatch", "certainty_inflation", "contradictory_evidence", "negation_reversal"])
def test_mapped_concern_disappearing_from_current_enum_fails_loudly(monkeypatch, concern):
    current = contracts.get_contracts()
    schemas = deepcopy(current.schemas)
    schemas["response"]["$defs"]["Concern"]["properties"]["type"]["enum"].remove(concern)
    monkeypatch.setattr(contracts, "get_contracts", lambda: replace(current, schemas=schemas))
    with pytest.raises(ValueError, match=concern):
        loader().load_mapping()


@pytest.mark.parametrize(
    "patch",
    [
        {"mapping_version": "1.0"},
        {"mapping_version": "01.0.0"},
        {"mapping_version": "1.0.0-01"},
        {"mapping_version": 1},
        {"types": {"X": {"allowed": ["made_up"]}}},
        {"types": {"X": {"allowed": ["unsupported_claim"], "datasets": ["unknown"]}}},
        {"types": {"X": {"allowed": ["unsupported_claim"], "dataset_overrides": {"unknown": []}}}},
        {"types": {"X": {"allowed": ["unsupported_claim"], "dataset_overrides": {"meetingbank": ["made_up"]}}}},
        {"types": {"X": {"allowed": ["unsupported_claim"], "recall_only": True}}},
        {"types": {"X": {"allowed": None}}},
        {"types": {"X": {"allowed": "unsupported_claim"}}},
        {"types": {"X": {"allowed": ["unsupported_claim"], "datasets": "mediasum"}}},
        {"types": {"X": {"allowed": None, "recall_only": "true"}}},
        {"unexpected": True},
    ],
)
def test_invalid_mapping_contents_are_rejected(tmp_path, patch):
    module = loader()
    raw = json.loads(MAPPING.read_text())
    raw.update(patch)
    path = tmp_path / "mapping.json"
    path.write_text(json.dumps(raw))
    with pytest.raises(ValueError):
        module.load_mapping(path)


@pytest.mark.parametrize("version", ["2.0.0", "1.2.3-alpha.1+build.01"])
def test_valid_semver_is_accepted(tmp_path, version):
    module = loader()
    raw = json.loads(MAPPING.read_text())
    raw["mapping_version"] = version
    path = tmp_path / "mapping.json"
    path.write_text(json.dumps(raw))
    assert module.load_mapping(path).mapping_version == version


def test_unknown_lookup_dataset_and_type_fail_instead_of_silently_skipping():
    mapping = loader().load_mapping()
    with pytest.raises(ValueError, match="dataset"):
        mapping.applicable_allowed("Contradiction", "unknown")
    with pytest.raises(ValueError, match="type"):
        mapping.applicable_allowed("Typo", "mediasum")
