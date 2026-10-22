"""Offline summary loading rejects ambiguity and preserves raw sentence gold."""

import csv
import importlib.util
import json
import re
import shutil
import sys
from hashlib import sha256
from pathlib import Path

import pytest

FIXTURES = Path(__file__).with_name("fixtures")
MODULE = Path(__file__).resolve().parents[3] / "datasets/tofueval/items.py"


def loader():
    assert MODULE.is_file(), "TofuEval item loader is not implemented"
    # Give relative sibling imports a real package without changing the registry.
    package_spec = importlib.util.spec_from_file_location(
        "fictional_tofueval", MODULE, submodule_search_locations=[str(MODULE.parent)]
    )
    module = importlib.util.module_from_spec(package_spec)
    sys.modules[package_spec.name] = module
    package_spec.loader.exec_module(module)
    return module


@pytest.fixture
def repo(tmp_path):
    return Path(shutil.copytree(FIXTURES / "repo", tmp_path / "repo"))


def rewrite_rows(repo, mutate, dataset="meetingbank", split="dev"):
    path = repo / "factual_consistency" / f"{dataset}_factual_eval_{split}.csv"
    with path.open(newline="", encoding="utf-8") as stream:
        reader = csv.DictReader(stream)
        fields, rows = reader.fieldnames, list(reader)
    mutate(rows)
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def test_grouping_offsets_raw_gold_and_slice_attributes(repo):
    items = loader().load_items(repo)
    assert len(items) == 5
    assert len({item.id for item in items}) == 5
    assert len({item.doc_id for item in items}) == 4
    ms = next(item for item in items if item.doc_id == "FICTIONAL-MS-DEV")
    assert ms.id == "mediasum--fictional-ms-dev--fictional-kite-exhibition--model-a"
    assert ms.split == "dev"
    assert ms.meta == {
        "dataset": "mediasum",
        "topic": "Fictional kite exhibition",
        "topic_category": "main",
        "model_name": "model_A",
        "model_group": "original_five",
        "is_extra": False,
        "has_gaps": True,
    }
    sentences = ms.payload["sentences"]
    assert [sentence["sent_idx"] for sentence in sentences] == [1, 9, 10]
    assert [(s["start"], s["end"]) for s in sentences] == [(0, 78), (79, 122), (123, 166)]
    assert sentences[0]["text"] == (
        "The fictional café hosts a kite exhibition.\nPaper birds hang above the tables."
    )
    assert sentences[1] == {
        "sent_idx": 9,
        "text": "The fictional exhibition opens before dawn.",
        "label": "no",
        "types": ["Contradiction", "Tense/Modality Error"],
        "exp": "The fictional speaker says it opens at noon.",
        "contamination_identifier": "fictional-token-9",
        "start": 79,
        "end": 122,
    }
    assert all(item.split == "test" for item in items if item.doc_id.endswith("TEST"))
    assert all(not item.meta["has_gaps"] for item in items if item.split == "test")


def test_duplicate_keeps_first_and_records_provenance(repo):
    records = []
    items = loader().load_items(repo, duplicate_records=records)
    extra = next(item for item in items if item.meta["is_extra"])
    assert extra.meta["model_group"] == "model_extra"
    assert [s["sent_idx"] for s in extra.payload["sentences"]] == [1, 3]
    assert extra.payload["sentences"][0]["contamination_identifier"] == "fictional-first"
    assert records == [
        {
            "dataset": "meetingbank",
            "doc_id": "FictionalCouncil 24-0001",
            "topic": "Fictional lantern schedule",
            "model_name": "Model-Extra",
            "sent_idx": 1,
            "file": "factual_consistency/meetingbank_factual_eval_dev.csv",
            "kept_row": 2,
            "duplicate_row": 3,
        }
    ]
    json.dumps(records)  # Task 6 can include these records directly in the manifest.


@pytest.mark.parametrize(
    "field,value", [("summ_sent", "Conflicting fictional text."), ("sent_label", "no")]
)
def test_conflicting_duplicate_raises(repo, field, value):
    rewrite_rows(repo, lambda rows: rows[1].update({field: value}))
    with pytest.raises(ValueError, match="[Cc]onflicting duplicate.*sent_idx.*1"):
        loader().load_items(repo)


def test_missing_topic_is_error(repo):
    path = repo / "topic_category/meetingbank_topic_category.json"
    topics = json.loads(path.read_text())
    del topics["Fictional lantern schedule"]
    path.write_text(json.dumps(topics))
    with pytest.raises(ValueError, match="[Mm]issing topic.*Fictional lantern schedule"):
        loader().load_items(repo)


def test_long_ids_are_bounded_hash_suffixed_stable_and_distinguish_suffixes(repo):
    module = loader()
    first = module.load_items(repo)
    long_item = next(item for item in first if len(item.meta["topic"]) > 100)
    full = (
        "meetingbank--fictionalcouncil-24-0001--"
        + re.sub(r"[^a-z0-9]+", "-", long_item.meta["topic"].lower()).strip("-")
        + "--model-a"
    )
    assert long_item.id == full[:119] + "-" + sha256(full.encode()).hexdigest()[:8]
    assert len(long_item.id) == 128
    assert all(re.fullmatch(r"[A-Za-z0-9._-]{1,128}", item.id) for item in first)
    assert module.load_items(repo) == first
    topic_path = repo / "topic_category/meetingbank_topic_category.json"
    topics = json.loads(topic_path.read_text())
    changed = long_item.meta["topic"] + " alternate fictional ending"
    topics[changed] = "marginal"
    topic_path.write_text(json.dumps(topics))

    def add_long(rows):
        row = dict(rows[-1], topic=changed)
        rows.append(row)

    rewrite_rows(repo, add_long)
    second = module.load_items(repo)
    assert len(second) == len({item.id for item in second}) == 6
    assert sum(len(item.id) == 128 for item in second) == 2


def test_slug_collision_is_error(repo):
    def add_collision(rows):
        rows.append(dict(rows[-1], model_name="model A"))

    rewrite_rows(repo, add_collision, dataset="mediasum")
    with pytest.raises(ValueError, match="[Dd]uplicate item id"):
        loader().load_items(repo)


def test_split_index_reusable_with_raw_ids(repo):
    index = loader().load_split_index(repo / "document_ids_dev_test_split.json")
    assert index == {
        ("mediasum", "FICTIONAL-MS-DEV"): "dev",
        ("meetingbank", "FictionalCouncil 24-0001"): "dev",
        ("mediasum", "FICTIONAL-MS-TEST"): "test",
        ("meetingbank", "FictionalCouncil 24-0002"): "test",
    }


@pytest.mark.parametrize(
    "change", ["missing", "wrong_split", "cross_dataset", "duplicate", "cross_split", "shape"]
)
def test_invalid_split_index_or_inconsistent_csv_fails(repo, change):
    path = repo / "document_ids_dev_test_split.json"
    data = json.loads(path.read_text())
    if change == "missing":
        data["dev"]["mediasum"] = []
    elif change == "wrong_split":
        data["test"]["mediasum"].append(data["dev"]["mediasum"].pop())
    elif change == "cross_dataset":
        data["dev"]["meetingbank"].append("FICTIONAL-MS-DEV")
    elif change == "duplicate":
        data["dev"]["mediasum"].append("FICTIONAL-MS-DEV")
    elif change == "cross_split":
        data["test"]["mediasum"].append("FICTIONAL-MS-DEV")
    else:
        data["dev"]["mediasum"] = "FICTIONAL-MS-DEV"
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError, match="[Ss]plit|[Dd]uplicate doc|[Mm]issing document"):
        loader().load_items(repo)


@pytest.mark.parametrize(
    "field,value",
    [
        ("sent_idx", "0"),
        ("sent_idx", "-1"),
        ("sent_idx", "1.5"),
        ("sent_label", "maybe"),
        ("model_name", ""),
        ("summ_sent", ""),
        ("topic", ""),
    ],
)
def test_malformed_rows_fail_explicitly(repo, field, value):
    rewrite_rows(repo, lambda rows: rows[0].update({field: value}), dataset="mediasum")
    with pytest.raises(ValueError, match=field):
        loader().load_items(repo)


def test_truncated_csv_row_rejected(repo):
    path = repo / "factual_consistency/mediasum_factual_eval_test.csv"
    with path.open("a") as stream:
        stream.write("FICTIONAL-MS-TEST,too,few,columns\n")
    with pytest.raises(ValueError, match="[Mm]alformed.*row"):
        loader().load_items(repo)


def test_first_sentence_index_above_one_is_a_gap(repo):
    rewrite_rows(repo, lambda rows: rows[0].update(sent_idx="2"), dataset="mediasum", split="test")
    item = next(item for item in loader().load_items(repo) if item.doc_id == "FICTIONAL-MS-TEST")
    assert item.meta["has_gaps"] is True
    assert item.payload["sentences"][0]["start"] == 0


@pytest.mark.parametrize(
    "value", [[], {"Fictional lantern schedule": []}, {"Fictional lantern schedule": "unknown"}]
)
def test_malformed_topic_maps_fail_explicitly(repo, value):
    path = repo / "topic_category/meetingbank_topic_category.json"
    path.write_text(json.dumps(value))
    with pytest.raises(ValueError, match="[Ii]nvalid topic category"):
        loader().load_items(repo)


def test_missing_csv_column_rejected(repo):
    path = repo / "factual_consistency/mediasum_factual_eval_test.csv"
    path.write_text("doc_id,topic\nFICTIONAL-MS-TEST,Fictional moonseed delivery\n")
    with pytest.raises(ValueError, match="[Mm]alformed CSV header"):
        loader().load_items(repo)


def test_raw_document_id_is_not_normalized(repo):
    rewrite_rows(
        repo,
        lambda rows: rows[0].update(doc_id="FICTIONAL-MS-TEST "),
        dataset="mediasum",
        split="test",
    )
    with pytest.raises(ValueError, match="[Mm]issing document"):
        loader().load_items(repo)


def test_failed_load_does_not_publish_partial_duplicate_records(repo):
    rewrite_rows(repo, lambda rows: rows[-1].update(sent_label="invalid"))
    duplicates = []
    with pytest.raises(ValueError, match="sent_label"):
        loader().load_items(repo, duplicate_records=duplicates)
    assert duplicates == []


def test_unknown_gold_error_type_fails_at_load_naming_file_and_row(repo):
    def mutate(rows):
        rows[0]["type"] = "Fictional Bogus Type"

    rewrite_rows(repo, mutate)
    with pytest.raises(ValueError, match=r"Unknown gold error type 'Fictional Bogus Type'.*"
                                         r"meetingbank_factual_eval_dev\.csv row 2"):
        loader().load_items(repo)
