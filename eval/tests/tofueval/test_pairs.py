"""Fictional offline pair populations; expected results are hand-computed."""

import importlib
from copy import deepcopy
from pathlib import Path

import pytest

from iaudit_eval.datasets import Item
from iaudit_eval.metrics.pair import LevelSpec
from iaudit_eval.metrics.policy import apply

EVAL = Path(__file__).resolve().parents[2]


def emit(monkeypatch, item, gold, prediction, failure=None):
    path = EVAL / "datasets/tofueval/pairs.py"
    assert path.is_file(), "TofuEval pairs emission is not implemented"
    monkeypatch.syspath_prepend(str(EVAL))
    return importlib.import_module("datasets.tofueval.pairs").pairs(
        item, gold, prediction, failure,
    )


def fixture(dataset="mediasum"):
    item = Item("fictional-pairs", "fictional-doc", "dev", {}, {
        "dataset": dataset, "topic": "Fictional birds", "topic_category": "main",
        "model_group": "original_five", "model_name": "fictional-model",
    })
    gold = {"summary": "inconsistent", "sentences": [
        {"sent_idx": 2, "label": "inconsistent", "types": ["Extrinsic Information", "Tense/Modality Error"], "text": "Fictional sentence.", "exp": "Fictional explanation."},
        {"sent_idx": 5, "label": "consistent", "types": [], "text": "Fictional sentence.", "exp": "Fictional explanation."},
        {"sent_idx": 9, "label": "inconsistent", "types": ["Mis-Referencing", "Stating Opinion as Fact"], "text": "Fictional sentence.", "exp": "Fictional explanation."},
        {"sent_idx": 12, "label": "inconsistent", "types": ["Contradiction"], "text": "Fictional sentence.", "exp": "Fictional explanation."},
    ]}
    pred = {"summary": "inconsistent", "sentences": [
        {"sent_idx": 2, "label": "inconsistent", "meta": False, "claim_ids": ["c1", "c2"], "concerns": ["unsupported_claim", "certainty_inflation"], "boundary": True},
        {"sent_idx": 5, "label": "consistent", "meta": True, "claim_ids": ["c2"], "concerns": ["unsupported_claim"], "boundary": True},
        {"sent_idx": 9, "label": "consistent", "meta": False, "claim_ids": ["c3"], "concerns": ["wrong_attribution"], "boundary": False},
        {"sent_idx": 12, "label": "unresolved", "meta": False, "claim_ids": [], "concerns": [], "boundary": False},
    ], "claims_total": 4, "claims_unmapped": 1, "claims_boundary_crossing": 1,
        "concern_not_in_mapping": {"quantity_mismatch": 2}}
    return item, gold, pred


def at(pairs, level):
    return [pair for pair in pairs if pair.level == level]


def test_native_pairs_keep_unresolved_for_b3_policies_and_multilabel_flags(monkeypatch):
    result = emit(monkeypatch, *fixture())
    sentences = at(result, "sentence")
    assert [(p.unit, p.gold, p.pred, p.failure) for p in sentences] == [
        ("2", "inconsistent", "inconsistent", None),
        ("5", "consistent", "consistent", None),
        ("9", "inconsistent", "consistent", None),
        ("12", "inconsistent", None, "unresolved"),
    ]
    assert sentences[0].meta["type_EI"] is True
    assert sentences[0].meta["type_TAM"] is True
    assert sentences[0].meta["type_MR"] is False
    assert [(p.gold, p.pred) for p in at(result, "summary")] == [("inconsistent", "inconsistent")]
    assert all((p.pred is None) == (p.failure == "unresolved") for p in result)
    spec = LevelSpec(("consistent", "inconsistent"), "inconsistent")
    assert apply(sentences, spec, "primary")[-1].pred == "consistent"
    assert len(apply(sentences, spec, "secondary")) == 3


def test_concern_populations_match_union_and_do_not_condition_recall_on_detection(monkeypatch):
    result = emit(monkeypatch, *fixture())
    assert [(p.unit, p.gold, p.pred, p.meta["concern_population"]) for p in at(result, "concern:EI")] == [
        ("2", True, True, "gold_inconsistent"), ("5", True, True, "gold_consistent"),
    ]
    assert [(p.unit, p.pred) for p in at(result, "concern:TAM")] == [("2", True), ("5", False)]
    assert [(p.unit, p.pred) for p in at(result, "concern:MR")] == [("5", False), ("9", True)]
    assert [(p.unit, p.pred, p.failure) for p in at(result, "concern:CO")] == [
        ("5", False, None), ("12", None, "unresolved"),
    ]
    assert [(p.unit, p.pred) for p in at(result, "concern_detected:EI")] == [("2", True)]
    assert [(p.unit, p.pred) for p in at(result, "concern_detected:TAM")] == [("2", True)]
    assert at(result, "concern_detected:MR") == []
    assert at(result, "concern_detected:CO") == []
    assert all(p.gold is True for p in result if p.level.startswith("concern"))


def test_meetingbank_excludes_misreferencing_and_wrong_attribution_for_opinion(monkeypatch):
    result = emit(monkeypatch, *fixture("meetingbank"))
    assert at(result, "concern:MR") == []
    assert at(result, "concern_detected:MR") == []
    assert [(p.unit, p.pred) for p in at(result, "concern:OF")] == [("5", False), ("9", False)]
    assert at(result, "sentence")[2].meta["type_MR"] is True  # recall remains applicable


def test_meta_alternative_reaggregates_summary_independently(monkeypatch):
    item, gold, pred = fixture()
    pred["sentences"] = pred["sentences"][:2]
    gold["sentences"] = gold["sentences"][:2]
    pred["sentences"][0]["label"] = "consistent"
    pred["summary"] = "consistent"
    result = emit(monkeypatch, item, gold, pred)
    assert at(result, "summary")[0].pred == "consistent"
    assert at(result, "summary_meta_unresolved")[0].pred is None
    assert at(result, "summary_meta_unresolved")[0].failure == "unresolved"
    assert [(p.pred, p.failure) for p in at(result, "sentence_meta_unresolved")] == [
        ("consistent", None), (None, "unresolved"),
    ]
    # A detected inconsistent sentence outranks meta-unresolved in summary aggregation.
    pred["sentences"][0]["label"] = "inconsistent"
    pred["summary"] = "inconsistent"
    assert at(emit(monkeypatch, item, gold, pred), "summary_meta_unresolved")[0].pred == "inconsistent"


@pytest.mark.parametrize("failure", ["item_failed", "unmapped", "unresolved"])
def test_failed_items_still_emit_gold_units_all_unresolved(monkeypatch, failure):
    item, gold, _ = fixture()
    result = emit(monkeypatch, item, gold, None, failure)
    assert len(at(result, "sentence")) == 4
    assert len(at(result, "summary")) == 1
    assert all(p.pred is None and p.failure == "unresolved" for p in result)
    assert not any(p.level.startswith("concern_detected:") for p in result)
    assert at(result, "summary")[0].meta["claims_total"] == 0
    assert at(result, "summary")[0].meta["sentences_total"] == 4


def test_scalar_diagnostics_once_per_item_and_slices_preserve_group(monkeypatch):
    result = emit(monkeypatch, *fixture())
    summary = at(result, "summary")[0]
    assert {k: summary.meta[k] for k in ("claims_total", "claims_unmapped", "claims_boundary_crossing", "sentences_total", "concern_not_in_mapping:quantity_mismatch")} == {
        "claims_total": 4, "claims_unmapped": 1, "claims_boundary_crossing": 1,
        "sentences_total": 4, "concern_not_in_mapping:quantity_mismatch": 2,
    }
    assert sum(p.meta.get("claims_total", 0) for p in result) == 4
    assert [p.meta["claims_mapped"] for p in at(result, "sentence")] == [2, 1, 1, 0]
    assert sum(p.meta.get("meta_consistent_n", 0) for p in result) == 1
    for p in result:
        assert p.cluster == "fictional-doc" and p.item_id == "fictional-pairs"
        assert p.meta["group_dataset"] == "original_five|mediasum"
        assert p.meta["group_topic"] == "original_five|mediasum|main"
        assert p.meta["group_model"] == "original_five|fictional-model"
        assert p.meta["topic"] == "Fictional birds"
        assert "text" not in p.meta and "exp" not in p.meta


def test_pairs_snapshot_inputs_without_mutation(monkeypatch):
    item, gold, pred = fixture()
    item.meta["custom"] = {"labels": ["fictional"]}
    original = deepcopy((item, gold, pred))
    result = emit(monkeypatch, item, gold, pred)
    assert (item, gold, pred) == original
    item.meta["custom"]["labels"].append("later")
    assert result[0].meta["custom"] == {"labels": ["fictional"]}


def test_unknown_gold_type_raises_like_item_rows(monkeypatch):
    item, gold, _ = fixture()
    gold["sentences"][0]["types"] = ["Fictional Bogus Type"]
    with pytest.raises(ValueError, match="Unknown TofuEval error type"):
        emit(monkeypatch, item, gold, None, "item_failed")
