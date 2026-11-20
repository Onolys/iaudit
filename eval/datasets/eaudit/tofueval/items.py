"""Load local TofuEval summary items without projecting or changing raw gold."""

from __future__ import annotations

import csv
import json
import re
from hashlib import sha256
from pathlib import Path
from typing import Any

from iaudit_eval.datasets.base import ID_RE, Item

from .assessment import build_assessment
from .mapping import load_mapping

_DATASETS = ("mediasum", "meetingbank")
_SPLITS = ("dev", "test")
_COLUMNS = {
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
}


def load_split_index(path: Path) -> dict[tuple[str, str], str]:
    """Read split-first source JSON into ``(dataset, raw_doc_id) -> split``.

    Raw document IDs are globally unique across datasets and splits. Repeated
    summary rows for a document are allowed; duplicate entries here are ambiguous.
    """
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(raw, dict) or set(raw) != set(_SPLITS):
        raise ValueError(f"Split index {path} must contain dev and test objects")
    index: dict[tuple[str, str], str] = {}
    owners: dict[str, tuple[str, str]] = {}
    for split in _SPLITS:
        datasets = raw[split]
        if not isinstance(datasets, dict) or set(datasets) != set(_DATASETS):
            raise ValueError(f"Split {split} must contain mediasum and meetingbank lists")
        for dataset in _DATASETS:
            ids = datasets[dataset]
            if not isinstance(ids, list):
                raise ValueError(f"Split {split}/{dataset} document IDs must be a list")
            for doc_id in ids:
                if not isinstance(doc_id, str) or not doc_id.strip():
                    raise ValueError(f"Split {split}/{dataset} has an invalid document ID")
                if doc_id in owners:
                    raise ValueError(
                        f"Duplicate doc_id {doc_id!r}: {owners[doc_id]} and {(dataset, split)}"
                    )
                owners[doc_id] = (dataset, split)
                index[(dataset, doc_id)] = split
    return index


def _item_id(key: tuple[str, str, str, str]) -> str:
    full = "--".join(re.sub(r"[^a-z0-9]+", "-", part.lower()).strip("-") for part in key)
    value = full if len(full) <= 128 else full[:119] + "-" + sha256(full.encode()).hexdigest()[:8]
    if not ID_RE.fullmatch(value):
        raise ValueError(f"Invalid item id {value!r}")
    return value


def load_items(
    repo_dir: Path,
    *,
    duplicate_records: list[dict[str, Any]] | None = None,
) -> list[Item]:
    """Group all four CSVs, validate joins and return deterministic summary items.

    ``repo_dir`` contains ``factual_consistency/``, ``topic_category/`` and the
    split JSON. Duplicate records are appended only after a successful load and
    include CSV record numbers (header = 1), never summary text or explanations.
    The optional list can be incorporated directly into the download manifest.
    """
    repo_dir = Path(repo_dir)
    split_index = load_split_index(repo_dir / "document_ids_dev_test_split.json")
    mapping = load_mapping()
    groups: dict[tuple[str, str, str, str], dict[int, dict[str, Any]]] = {}
    provenance: dict[tuple[tuple[str, str, str, str], int], tuple[str, int]] = {}
    duplicates: list[dict[str, Any]] = []
    category_maps: dict[str, dict[str, str]] = {}
    for dataset in _DATASETS:
        path = repo_dir / "topic_category" / f"{dataset}_topic_category.json"
        categories = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(categories, dict) or any(
            not isinstance(topic, str) or category not in ("main", "marginal")
            for topic, category in categories.items()
        ):
            raise ValueError(f"Invalid topic category map: {path}")
        category_maps[dataset] = categories
        for split in _SPLITS:
            relative = f"factual_consistency/{dataset}_factual_eval_{split}.csv"
            with (repo_dir / relative).open(newline="", encoding="utf-8") as stream:
                reader = csv.DictReader(stream)
                if (
                    reader.fieldnames is None
                    or set(reader.fieldnames) != _COLUMNS
                    or len(reader.fieldnames) != len(_COLUMNS)
                ):
                    raise ValueError(f"Malformed CSV header in {relative}")
                for row_number, row in enumerate(reader, start=2):
                    location = f"{relative} row {row_number}"
                    if set(row) != _COLUMNS or any(value is None for value in row.values()):
                        raise ValueError(f"Malformed CSV row in {location}")
                    for field in ("doc_id", "topic", "model_name", "summ_sent"):
                        if not row[field].strip():
                            raise ValueError(f"Invalid {field} in {location}")
                    if not re.fullmatch(r"[0-9]+", row["sent_idx"]) or int(row["sent_idx"]) < 1:
                        raise ValueError(f"Invalid sent_idx in {location}: {row['sent_idx']!r}")
                    if row["sent_label"] not in {"yes", "no"}:
                        raise ValueError(f"Invalid sent_label in {location}: {row['sent_label']!r}")
                    for name in (part.strip() for part in row["type"].split(",")):
                        if name and not mapping.is_known_type(name):
                            raise ValueError(f"Unknown gold error type {name!r} in {location}")
                    doc_id, topic, model = row["doc_id"], row["topic"], row["model_name"]
                    assigned_split = split_index.get((dataset, doc_id))
                    if assigned_split is None:
                        raise ValueError(f"Missing document {dataset}/{doc_id!r} in split index")
                    if assigned_split != split:
                        raise ValueError(
                            f"Split mismatch for {dataset}/{doc_id!r}: "
                            f"index={assigned_split}, CSV={split}"
                        )
                    if topic not in categories:
                        raise ValueError(f"Missing topic {topic!r} in {dataset} category map")
                    key = (dataset, doc_id, topic, model)
                    sent_idx = int(row["sent_idx"])
                    sentence = {
                        "sent_idx": sent_idx,
                        "text": row["summ_sent"],
                        "label": row["sent_label"],
                        "types": [part.strip() for part in row["type"].split(",") if part.strip()],
                        "exp": row["exp"],
                        "contamination_identifier": row["contamination_identifier"],
                    }
                    group = groups.setdefault(key, {})
                    if sent_idx in group:
                        previous = group[sent_idx]
                        if any(previous[field] != sentence[field] for field in ("text", "label")):
                            raise ValueError(f"Conflicting duplicate {key!r}, sent_idx={sent_idx}")
                        kept_file, kept_row = provenance[(key, sent_idx)]
                        duplicates.append(
                            {
                                "dataset": dataset,
                                "doc_id": doc_id,
                                "topic": topic,
                                "model_name": model,
                                "sent_idx": sent_idx,
                                "file": kept_file,
                                "kept_row": kept_row,
                                "duplicate_row": row_number,
                            }
                        )
                    else:
                        group[sent_idx] = sentence
                        provenance[(key, sent_idx)] = (relative, row_number)

    items: list[Item] = []
    seen_ids: set[str] = set()
    for key, sentences in sorted(groups.items()):
        dataset, doc_id, topic, model = key
        item_id = _item_id(key)
        if item_id in seen_ids:
            raise ValueError(f"Duplicate item id {item_id!r} for source group {key!r}")
        seen_ids.add(item_id)
        _, positioned = build_assessment(sentences.values())
        indices = [sentence["sent_idx"] for sentence in positioned]
        is_extra = model == "Model-Extra"
        items.append(
            Item(
                id=item_id,
                doc_id=doc_id,
                split=split_index[(dataset, doc_id)],
                payload={"sentences": positioned},
                meta={
                    "dataset": dataset,
                    "topic": topic,
                    "topic_category": category_maps[dataset][topic],
                    "model_name": model,
                    "model_group": "model_extra" if is_extra else "original_five",
                    "is_extra": is_extra,
                    "has_gaps": any(index != expected for expected, index in enumerate(indices, 1)),
                },
            )
        )
    if duplicate_records is not None:
        duplicate_records.extend(duplicates)
    return items
