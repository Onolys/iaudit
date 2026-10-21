"""Keep the offline source stand-ins loadable and their edge cases intact."""

import csv
import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from zipfile import ZipFile

FIXTURES = Path(__file__).with_name("fixtures")
COLUMNS = [
    "doc_id",
    "annotation_id",
    "topic",
    "model_name",
    "sent_idx",
    "summ_sent",
    "sent_label",
    "exp",
    "type",
    "contamination_identifier",
]


def read_rows():
    rows = []
    for dataset in ("mediasum", "meetingbank"):
        for split in ("dev", "test"):
            path = FIXTURES / "repo" / "factual_consistency" / f"{dataset}_factual_eval_{split}.csv"
            with path.open(newline="", encoding="utf-8") as stream:
                reader = csv.DictReader(stream)
                assert reader.fieldnames == COLUMNS
                contents = list(reader)
            assert contents
            rows.extend((dataset, split, row) for row in contents)
    return rows


def test_fictional_csvs_resolve_against_topic_maps_and_document_splits():
    splits = json.loads((FIXTURES / "repo/document_ids_dev_test_split.json").read_text())
    assert set(splits) == {"dev", "test"}
    assert all(set(value) == {"mediasum", "meetingbank"} for value in splits.values())
    for dataset, split, row in read_rows():
        categories = json.loads(
            (FIXTURES / f"repo/topic_category/{dataset}_topic_category.json").read_text()
        )
        assert categories[row["topic"]] in {"main", "marginal"}
        assert row["doc_id"] in splits[split][dataset]
        assert row["sent_label"] in {"yes", "no"}
        assert int(row["sent_idx"]) >= 1
        assert "fictional" in row["summ_sent"].lower()
        assert not row["exp"] or "fictional" in row["exp"].lower()
    for dataset in ("mediasum", "meetingbank"):
        assert set(splits["dev"][dataset]).isdisjoint(splits["test"][dataset])


def test_csvs_preserve_numeric_order_gaps_newline_and_long_item_id_cases():
    groups = defaultdict(list)
    for dataset, _, row in read_rows():
        groups[(dataset, row["doc_id"], row["topic"], row["model_name"])].append(row)
    indices = [{int(row["sent_idx"]) for row in rows} for rows in groups.values()]
    assert {1, 9, 10} in indices  # Lexicographic order must differ from numeric order.
    assert {1, 3} in indices
    assert any("\n" in row["summ_sent"] for rows in groups.values() for row in rows)
    assert any("café" in row["summ_sent"] for rows in groups.values() for row in rows)
    assert any(
        len("--".join(re.sub(r"[^a-z0-9]+", "-", part.lower()).strip("-") for part in key)) > 128
        for key in groups
    )


def test_one_duplicate_differs_only_in_contamination_identifier():
    rows = [row for _, _, row in read_rows()]
    keys = Counter(
        (row["doc_id"], row["topic"], row["model_name"], row["sent_idx"]) for row in rows
    )
    duplicate_keys = [key for key, count in keys.items() if count > 1]
    assert len(duplicate_keys) == 1
    assert keys[duplicate_keys[0]] == 2
    duplicate_rows = [
        row
        for row in rows
        if (row["doc_id"], row["topic"], row["model_name"], row["sent_idx"]) == duplicate_keys[0]
    ]
    first, second = duplicate_rows
    assert first["contamination_identifier"] != second["contamination_identifier"]
    assert {key: value for key, value in first.items() if key != "contamination_identifier"} == {
        key: value for key, value in second.items() if key != "contamination_identifier"
    }


def test_mediasum_archive_has_complete_jsonl_records_and_repeated_generic_labels():
    with ZipFile(FIXTURES / "mediasum/test_data.zip") as archive:
        with archive.open("test_data.txt") as stream:
            records = [json.loads(line) for line in stream]
    assert len(records) >= 2
    for record in records:
        assert set(record) == {"id", "program", "date", "url", "title", "summary", "utt", "speaker"}
        assert len(record["speaker"]) == len(record["utt"])
        assert all(record["speaker"])
        assert all("fictional" in text.lower() for text in record["utt"])
    assert any(record["speaker"].count("Unidentified Male") >= 2 for record in records)
    splits = json.loads((FIXTURES / "repo/document_ids_dev_test_split.json").read_text())
    assert {record["id"] for record in records} == {
        doc_id for split in splits.values() for doc_id in split["mediasum"]
    }


def test_meetingbank_is_jsonl_with_raw_uid_and_sentence_chunking_edges():
    with (FIXTURES / "meetingbank/test.json").open(encoding="utf-8") as stream:
        records = [json.loads(line) for line in stream]
    assert len(records) >= 2
    for record in records:
        assert set(record) == {"summary", "uid", "id", "transcript"}
        assert isinstance(record["id"], int)
        assert "fictional" in record["transcript"].lower()
    assert any(" " in record["uid"] for record in records)
    assert any("  " in record["transcript"] for record in records)
    lengths = [
        len(sentence.split())
        for record in records
        for sentence in re.split(r"(?<=[.!?])\s+", record["transcript"])
    ]
    assert any(length > 60 for length in lengths)
    assert sum(30 < length <= 60 for length in lengths) >= 2
    splits = json.loads((FIXTURES / "repo/document_ids_dev_test_split.json").read_text())
    assert {record["uid"] for record in records} == {
        doc_id for split in splits.values() for doc_id in split["meetingbank"]
    }
