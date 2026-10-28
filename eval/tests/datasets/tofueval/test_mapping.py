"""The frozen mapping rejects drift without rejecting future predictions."""

import importlib.util
import json
import sys
from copy import deepcopy
from dataclasses import replace
from hashlib import sha256
from pathlib import Path

import pytest

from iaudit_eval import contracts

ROOT = Path(__file__).resolve().parents[4]
MODULE = ROOT / "eval/datasets/eaudit/tofueval/mapping.py"
MAPPING = MODULE.with_suffix(".json")
CROSSWALK = {
    "Extrinsic Information": {"unsupported_claim", "question_as_answer"},
    "Mis-Referencing": {"wrong_attribution"},
    "Stating Opinion as Fact": {"opinion_as_fact"},
    "Tense/Modality": {"timeframe_mismatch", "certainty_inflation"},
    "Contradiction": {"contradictory_evidence", "negation_reversal"},
    "Reasoning Error": {"unsupported_causal_link", "calculation_error", "unsupported_inference"},
    "Nuanced Meaning Shift": {"meaning_shift"},
}
UNMAPPED = {
    "quantity_mismatch", "frequency_severity_inflation", "context_stripping",
    "correction_ignored", "conflicting_accounts_flattened",
}


def loader():
    assert MODULE.is_file(), "TofuEval frozen mapping loader is not implemented"
    spec = importlib.util.spec_from_file_location("fictional_tofueval_mapping", MODULE)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_mapping_version_digest_and_disjoint_crosswalk():
    raw = json.loads(MAPPING.read_text())
    mapping = loader().load_mapping()
    assert mapping.mapping_version == "0.0.1"
    assert mapping.sha256 == sha256(MAPPING.read_bytes()).hexdigest()
    assert set(raw["types"]) == set(CROSSWALK)
    concerns = [concern for rule in raw["types"].values() for concern in rule["allowed"]]
    assert len(concerns) == len(set(concerns))
    enum = set(contracts.get_contracts().schemas["response"]["$defs"]["Concern"]["properties"]["type"]["enum"])
    assert set(concerns) <= enum
    assert enum - mapping.mapped_concerns == UNMAPPED


@pytest.mark.parametrize("dataset", ["mediasum", "meetingbank"])
@pytest.mark.parametrize("error_type, allowed", CROSSWALK.items())
def test_applicable_allowed_honours_crosswalk_and_dataset_restriction(dataset, error_type, allowed):
    mapping = loader().load_mapping()
    expected = None if (error_type, dataset) == ("Mis-Referencing", "meetingbank") else allowed
    assert mapping.applicable_allowed(error_type, dataset) == expected
    for concern in mapping.mapped_concerns | UNMAPPED:
        assert mapping.matches(error_type, dataset, [concern]) == (expected is not None and concern in expected)


def test_unknown_predicted_concerns_are_ignored_for_matching():
    module = loader()
    mapping = module.load_mapping()
    assert not mapping.matches("Extrinsic Information", "mediasum", ["quantity_mismatch"])
    assert mapping.matches("Extrinsic Information", "mediasum", ["quantity_mismatch", "unsupported_claim"])
    assert not mapping.matches("Stating Opinion as Fact", "meetingbank", ["wrong_attribution"])
    assert not mapping.matches("Mis-Referencing", "meetingbank", ["wrong_attribution"])
    assert mapping.matches("Reasoning Error", "mediasum", ["unsupported_causal_link"])
    assert mapping.mapped_concerns == set().union(*CROSSWALK.values())
    assert module.matches("Tense/Modality Error", "mediasum", ["timeframe_mismatch"])
    assert module.applicable_allowed("Mis-Referencing", "meetingbank") is None
    assert module.normalize_type("Tense/Modality Error") == "Tense/Modality"
    assert module.normalize_type("Unknown Type") == "Unknown Type"


@pytest.mark.parametrize("concern", sorted(set().union(*CROSSWALK.values())))
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
