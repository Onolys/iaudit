"""Fictional, offline gold labels preserve local annotations without changing items."""

import importlib.util
import sys
from copy import deepcopy
from pathlib import Path

import pytest

from iaudit_eval.datasets import Item, list_datasets

EVAL = Path(__file__).resolve().parents[2]
DATASETS = EVAL / "datasets"
FIXTURES = EVAL / "tests/datasets/tofueval/fixtures/repo"


def module(name):
    path = DATASETS / f"tofueval/{name}.py"
    assert path.is_file(), f"TofuEval {name} is not implemented"
    spec = importlib.util.spec_from_file_location(
        f"fictional_gold_{name}", path, submodule_search_locations=[str(path.parent)]
    )
    loaded = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = loaded
    spec.loader.exec_module(loaded)
    return loaded


def item_with_labels(labels):
    return Item(
        id="fictional-gold", doc_id="fictional-doc", split="dev", meta={},
        payload={"sentences": [
            {
                "sent_idx": index,
                "text": "Fictional café.\n紙の鳥。",
                "label": label,
                "types": ["Contradiction", "Tense/Modality Error"] if label == "no" else [],
                "exp": "Fictional explanation: café\n紙。" if label == "no" else "",
                "start": (index - 1) * 21,
                "end": (index - 1) * 21 + 20,
                "contamination_identifier": "fictional-private-token",
            }
            for index, label in enumerate(labels, 1)
        ]},
    )


def test_gold_normalizes_raw_labels_and_preserves_verbatim_local_fields():
    item = item_with_labels(["yes", "no"])
    result = module("labels").gold(item)
    assert result == {
        "sentences": [
            {
                "sent_idx": 1, "text": "Fictional café.\n紙の鳥。", "label": "consistent",
                "types": [], "exp": "", "start": 0, "end": 20,
            },
            {
                "sent_idx": 2, "text": "Fictional café.\n紙の鳥。", "label": "inconsistent",
                "types": ["Contradiction", "Tense/Modality Error"],
                "exp": "Fictional explanation: café\n紙。", "start": 21, "end": 41,
            },
        ],
        "summary": "inconsistent",
    }


@pytest.mark.parametrize(
    "labels,expected",
    [
        (["yes"], "consistent"),
        (["yes", "yes"], "consistent"),
        (["no"], "inconsistent"),
        (["no", "yes"], "inconsistent"),
        (["yes", "no"], "inconsistent"),
        (["no", "no"], "inconsistent"),
    ],
)
def test_summary_is_inconsistent_iff_any_sentence_is_inconsistent(labels, expected):
    assert module("labels").gold(item_with_labels(labels))["summary"] == expected


def test_gold_does_not_mutate_or_alias_item_annotations():
    item = item_with_labels(["no"])
    original = deepcopy(item)
    result = module("labels").gold(item)
    assert item == original
    result["sentences"][0]["types"].append("Extrinsic Information")
    result["sentences"][0]["text"] = "Changed display text"
    assert item == original


@pytest.mark.parametrize("label", ["maybe", "YES", "no ", "consistent", "", None, True])
def test_invalid_raw_labels_are_rejected_without_guessing(label):
    with pytest.raises(ValueError, match="label"):
        module("labels").gold(item_with_labels([label]))


def test_gold_reads_c1_local_fixture_payload_with_gaps_and_multiple_types():
    item = next(
        item for item in module("items").load_items(FIXTURES)
        if item.doc_id == "FICTIONAL-MS-DEV"
    )
    result = module("labels").gold(item)
    assert [s["sent_idx"] for s in result["sentences"]] == [1, 9, 10]
    assert [s["label"] for s in result["sentences"]] == [
        "consistent", "inconsistent", "consistent",
    ]
    assert result["sentences"][0]["text"] == (
        "The fictional café hosts a kite exhibition.\nPaper birds hang above the tables."
    )
    assert result["sentences"][1] == {
        "sent_idx": 9,
        "text": "The fictional exhibition opens before dawn.",
        "label": "inconsistent",
        "types": ["Contradiction", "Tense/Modality Error"],
        "exp": "The fictional speaker says it opens at noon.",
        "start": 79, "end": 122,
    }
    assert result["summary"] == "inconsistent"


def test_gold_kind_is_exposed_for_on_demand_gold_display():
    meta = {entry.name: entry for entry in list_datasets(DATASETS)}["tofueval"]
    assert meta.gold_kind == "tofueval_summary_sentences"
    assert meta.to_dict()["gold_kind"] == "tofueval_summary_sentences"
