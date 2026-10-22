"""Assessment text and spans remain faithful to fictional summary sentences."""

import csv
import importlib.util
from copy import deepcopy
from pathlib import Path

import pytest

FIXTURES = Path(__file__).with_name("fixtures")
MODULE = Path(__file__).resolve().parents[3] / "datasets/tofueval/assessment.py"


def load_assessment():
    assert MODULE.is_file(), "TofuEval assessment builder is not implemented"
    spec = importlib.util.spec_from_file_location("tofueval_assessment", MODULE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def sentences():
    path = FIXTURES / "repo/factual_consistency/mediasum_factual_eval_dev.csv"
    with path.open(newline="", encoding="utf-8") as stream:
        return [
            {
                "sent_idx": row["sent_idx"],
                "text": row["summ_sent"],
                "label": row["sent_label"],
                "types": [value.strip() for value in row["type"].split(",") if value.strip()],
                "exp": row["exp"],
                "contamination_identifier": row["contamination_identifier"],
            }
            for row in csv.DictReader(stream)
        ]


def test_fixture_sort_gaps_and_newline_preserve_verbatim_text(sentences):
    assessment = load_assessment()
    section, positioned = assessment.build_assessment(sentences)

    assert section == {
        "id": "s0",
        "text": "The fictional café hosts a kite exhibition.\n"
        "Paper birds hang above the tables. "
        "The fictional exhibition opens before dawn. "
        "The fictional exhibition closes after dusk.",
    }
    assert [sentence["sent_idx"] for sentence in positioned] == [1, 9, 10]
    assert [(sentence["start"], sentence["end"]) for sentence in positioned] == [
        (0, 78), (79, 122), (123, 166),
    ]
    for sentence in positioned:
        assert section["text"][sentence["start"]:sentence["end"]] == sentence["text"]


def test_offsets_count_unicode_code_points_without_normalization():
    assessment = load_assessment()
    section, positioned = assessment.build_assessment([
        {"sent_idx": 3, "text": "End."},
        {"sent_idx": 1, "text": "🪁 e\u0301\n"},
    ])

    assert section == {"id": "s0", "text": "🪁 e\u0301\n End."}
    assert [(sentence["start"], sentence["end"]) for sentence in positioned] == [(0, 5), (6, 10)]


def test_gold_stays_in_copied_sentences_outside_request_section(sentences):
    assessment = load_assessment()
    original = deepcopy(sentences)
    section, positioned = assessment.build_assessment(sentences)

    assert sentences == original
    assert set(section) == {"id", "text"}
    assert positioned[1]["label"] == "no"
    assert positioned[1]["types"] == ["Contradiction", "Tense/Modality Error"]
    assert positioned[1]["exp"] == "The fictional speaker says it opens at noon."
    assert positioned[1]["contamination_identifier"] == "fictional-token-9"
    positioned[1]["types"].append("changed")
    assert sentences == original


@pytest.mark.parametrize("field,value", [("start", 1), ("end", 2), ("text", "corrupted")])
def test_corrupt_sentence_offset_or_text_raises(sentences, field, value):
    assessment = load_assessment()
    section, positioned = assessment.build_assessment(sentences)
    positioned[0][field] = value

    with pytest.raises(ValueError, match="Sentence 1.*offset"):
        assessment.assert_sentence_offsets(section["text"], positioned)
