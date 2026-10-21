"""Fictional offline rows: catch lost offsets, policy drift and leaked text."""

import importlib
import json
from copy import deepcopy
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from iaudit_eval.datasets import Item

EVAL = Path(__file__).resolve().parents[2]


def build(monkeypatch, item, gold, prediction, failure=None, mapping=None):
    assert (EVAL / "datasets/tofueval/item_rows.py").is_file(), "Item row builder missing"
    monkeypatch.syspath_prepend(str(EVAL))
    return importlib.import_module("datasets.tofueval.item_rows").build(
        item, gold, prediction, failure, mapping,
    )


def fixture(dataset="mediasum"):
    item = Item("fictional-item", "fictional-doc", "dev", {}, {
        "dataset": dataset, "topic": "Fictional topic", "topic_category": "main",
        "model_name": "fictional-model", "model_group": "original_five",
    })
    # Gold has 2 inconsistent sentences; predictions give TP,TN,FP,unresolved,TN,TN.
    labels = ["inconsistent", "consistent", "consistent", "inconsistent", "consistent", "consistent"]
    types = [["Extrinsic Information", "Nuanced Meaning Shift"], [], [], ["Tense/Modality Error"], [], []]
    gold = {"summary": "inconsistent", "sentences": [
        {"sent_idx": i * 2, "start": i * 20, "end": i * 20 + 19,
         "label": label, "types": error_types, "text": "Fictional secret sentence.",
         "exp": "Fictional secret explanation."}
        for i, (label, error_types) in enumerate(zip(labels, types, strict=True))
    ]}
    pred_labels = ["inconsistent", "consistent", "inconsistent", "unresolved", "consistent", "consistent"]
    pred = {"summary": "inconsistent", "sentences": [
        {"sent_idx": i * 2, "label": label, "meta": i == 4,
         "claim_ids": [] if i == 3 else [f"c{i}"],
         "verdicts": [] if i == 3 else ["out_of_scope" if i == 4 else "supported"],
         "concerns": ["unsupported_claim", "new_concern"] if i == 0 else [], "boundary": False}
        for i, label in enumerate(pred_labels)
    ], "claims_total": 5, "claims_unmapped": 0}
    return item, gold, pred


def test_worked_row_exact_shape_counts_and_no_source_text(monkeypatch):
    row = build(monkeypatch, *fixture())
    schema = json.loads((EVAL / "schemas/item_rows.schema.json").read_text())
    Draft202012Validator(schema).validate({"schema_version": "1.0.0", "run_id": "fictional", "rows": [row]})
    assert set(row) == {"item_id", "label", "status", "gold", "pred", "match", "outcome", "detail"}
    assert {k: row[k] for k in ("item_id", "label", "status", "gold", "pred", "match", "outcome")} == {
        "item_id": "fictional-item", "label": "fictional-doc / Fictional topic / fictional-model",
        "status": "ok", "gold": "inconsistent (2 of 6 sentences)",
        "pred": "inconsistent (2 of 6; 1 unresolved)", "match": True, "outcome": "tp",
    }
    detail = row["detail"]
    assert set(detail) == {"doc_id", "dataset", "topic_category", "model_name", "model_group", "gold", "pred", "sentences"}
    assert detail["gold"] == {"summary": "inconsistent", "n_sentences": 6, "n_inconsistent": 2, "types": ["Extrinsic Information", "Nuanced Meaning Shift", "Tense/Modality Error"]}
    assert detail["pred"] == {"summary": "inconsistent", "n_inconsistent": 2, "n_unresolved": 1, "n_meta": 1}
    assert [s["outcome"] for s in detail["sentences"]] == ["tp", "tn", "fp", "unresolved", "tn", "tn"]
    assert detail["sentences"][0] == {
        "sent_idx": 0, "start": 0, "end": 19, "gold_label": "inconsistent",
        "gold_types": ["Extrinsic Information", "Nuanced Meaning Shift"],
        "pred_label": "inconsistent", "meta": False, "claim_ids": ["c0"],
        "verdicts": ["supported"], "concerns": ["unsupported_claim", "new_concern"],
        "outcome": "tp", "concern_match": {"Extrinsic Information": True},
    }
    assert all(set(s) == set(detail["sentences"][0]) for s in detail["sentences"])
    serialized = json.dumps(row)
    assert '"text"' not in serialized and '"exp"' not in serialized and "secret" not in serialized


@pytest.mark.parametrize(("target", "prediction", "outcome", "match"), [
    ("inconsistent", "inconsistent", "tp", True), ("consistent", "consistent", "tn", True),
    ("consistent", "inconsistent", "fp", False), ("inconsistent", "consistent", "fn", False),
    ("inconsistent", "unresolved", "unresolved", None), ("consistent", "unresolved", "unresolved", None),
])
def test_summary_and_sentence_outcomes_share_primary_display_policy(monkeypatch, target, prediction, outcome, match):
    item, gold, pred = fixture()
    gold["sentences"] = gold["sentences"][:1]
    pred["sentences"] = pred["sentences"][:1]
    gold["summary"] = gold["sentences"][0]["label"] = target
    pred["summary"] = pred["sentences"][0]["label"] = prediction
    row = build(monkeypatch, item, gold, pred)
    assert (row["outcome"], row["match"], row["status"]) == (outcome, match, "ok")
    assert row["detail"]["sentences"][0]["outcome"] == outcome
    if prediction == "unresolved":
        assert row["pred"] == "unresolved (0 of 1; 1 unresolved)"


@pytest.mark.parametrize(("failure", "missing", "status"), [
    ("item_failed", True, "failed"), ("item_failed", False, "failed"),
    ("unmapped", True, "unmapped"), ("unmapped", False, "unmapped"), (None, True, "failed"),
])
def test_failure_keeps_gold_and_all_unresolved_without_made_up_claims(monkeypatch, failure, missing, status):
    item, gold, pred = fixture()
    row = build(monkeypatch, item, gold, None if missing else pred, failure)
    assert (row["status"], row["match"], row["outcome"]) == (status, None, "unresolved")
    assert row["pred"] == "unresolved (0 of 6; 6 unresolved)"
    assert row["detail"]["gold"]["n_inconsistent"] == 2
    assert row["detail"]["pred"] == {"summary": "unresolved", "n_inconsistent": 0, "n_unresolved": 6, "n_meta": 0}
    for sentence in row["detail"]["sentences"]:
        assert sentence["pred_label"] == sentence["outcome"] == "unresolved"
        assert sentence["meta"] is False
        assert sentence["claim_ids"] == sentence["verdicts"] == sentence["concerns"] == []
    assert row["detail"]["sentences"][0]["concern_match"] == {"Extrinsic Information": False}


@pytest.mark.parametrize(("dataset", "expected"), [
    ("mediasum", {"Mis-Referencing": True, "Stating Opinion as Fact": True, "Tense/Modality Error": True}),
    ("meetingbank", {"Stating Opinion as Fact": False, "Tense/Modality Error": True}),
])
def test_concern_matches_use_aliases_and_overrides_preserving_native_types(monkeypatch, dataset, expected):
    item, gold, pred = fixture(dataset)
    gold["sentences"][0]["types"] = ["Mis-Referencing", "Stating Opinion as Fact", "Tense/Modality Error", "Reasoning Error"]
    pred["sentences"][0]["concerns"] = ["wrong_attribution", "timeframe_mismatch"]
    row = build(monkeypatch, item, gold, pred)
    assert row["detail"]["sentences"][0]["concern_match"] == expected
    assert row["detail"]["sentences"][0]["gold_types"] == gold["sentences"][0]["types"]


def test_rows_join_by_id_and_snapshot_inputs_without_mutating_mapping(monkeypatch):
    monkeypatch.syspath_prepend(str(EVAL))
    mapping = importlib.import_module("datasets.tofueval.mapping").load_mapping()
    item, gold, pred = fixture()
    pred["sentences"].reverse()
    before = deepcopy((item, gold, pred))
    mapping_before = repr(mapping)
    row = build(monkeypatch, item, gold, pred, mapping=mapping)
    assert row["detail"]["sentences"][0]["claim_ids"] == ["c0"]
    assert (item, gold, pred) == before and repr(mapping) == mapping_before
    gold["sentences"][0]["types"].append("Contradiction")
    pred["sentences"][-1]["claim_ids"].append("later")
    assert row["detail"]["sentences"][0]["gold_types"] == ["Extrinsic Information", "Nuanced Meaning Shift"]
    assert row["detail"]["sentences"][0]["claim_ids"] == ["c0"]
