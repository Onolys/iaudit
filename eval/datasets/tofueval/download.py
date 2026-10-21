"""Transactional, pinned download of annotations and locally retained source data."""

from __future__ import annotations

import json
import os
import re
import shutil
import tempfile
import zipfile
from dataclasses import asdict
from pathlib import Path, PurePosixPath

import httpx

from iaudit_eval.download import FileRecord, _fetch, _hash_file, _now

from .items import load_items, load_split_index
from .transcripts import build_mediasum_turns, build_meetingbank_turns

_REQUIRED = {
    "document_ids_dev_test_split.json",
    *(
        f"factual_consistency/{dataset}_factual_eval_{split}.csv"
        for dataset in ("mediasum", "meetingbank")
        for split in ("dev", "test")
    ),
    *(f"topic_category/{dataset}_topic_category.json" for dataset in ("mediasum", "meetingbank")),
}


def _extract(archive: Path, destination: Path) -> None:
    """Write only required annotation files and root license/readme members."""
    seen = set()
    with zipfile.ZipFile(archive) as zipped:
        for member in zipped.infolist():
            parts = PurePosixPath(member.filename).parts
            if member.is_dir() or len(parts) < 2:
                continue
            relative = "/".join(parts[1:])
            if relative not in _REQUIRED and relative not in {"LICENSE", "README", "README.md"}:
                continue
            if relative in seen or member.external_attr >> 16 & 0o170000 == 0o120000:
                raise ValueError(f"Ambiguous archive member {relative!r}")
            seen.add(relative)
            target = destination / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            with zipped.open(member) as source, target.open("wb") as output:
                shutil.copyfileobj(source, output)
    if missing := _REQUIRED - seen:
        raise ValueError(f"Missing annotation files: {sorted(missing)}")


def _resolve(stream, dataset, wanted):
    selected = {}
    duplicate, ambiguous = set(), set()
    for line in stream:
        if not line.strip():
            continue
        row = json.loads(line)
        doc_id = row.get("id" if dataset == "mediasum" else "uid")
        if doc_id not in wanted:
            continue
        record = (
            {"speaker": row["speaker"], "utt": row["utt"]}
            if dataset == "mediasum"
            else {"transcript": row["transcript"]}
        )
        if doc_id in selected:
            (duplicate if record == selected[doc_id] else ambiguous).add(doc_id)
        else:
            selected[doc_id] = record
    missing = wanted - selected.keys()
    if missing or duplicate or ambiguous:
        raise ValueError(
            f"{dataset} ID resolution: missing={sorted(missing)}, "
            f"duplicate={sorted(duplicate)}, ambiguous={sorted(ambiguous)}"
        )
    for doc_id, record in selected.items():
        try:
            turns = (
                build_mediasum_turns(record["speaker"], record["utt"])
                if dataset == "mediasum"
                else build_meetingbank_turns(record["transcript"])
            )
            if not turns or any(not turn["text"].strip() for turn in turns):
                raise ValueError("empty transcript")
        except (AssertionError, TypeError, ValueError) as exc:
            raise ValueError(f"Invalid transcript for {dataset}/{doc_id}: {exc}") from exc
    return selected


def _json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8"
    )


def _promote(stage: Path, data_dir: Path):
    backup = stage.with_name(stage.name + "-backup")
    had_previous = data_dir.exists()
    if had_previous:
        os.replace(data_dir, backup)
    try:
        os.replace(stage, data_dir)
    except BaseException:
        if had_previous:
            os.replace(backup, data_dir)
        raise
    if had_previous:
        shutil.rmtree(backup)


def download(data_dir, progress, *, metadata=None, transport=None) -> list[FileRecord]:
    """Fetch and validate everything before replacing the last good snapshot.

    Tests may inject metadata and an httpx transport; the framework uses two args.
    HF main is resolved once per dataset snapshot and reused from its manifest.
    """
    data_dir = Path(data_dir)
    if metadata is None:
        metadata = json.loads(Path(__file__).with_name("metadata.json").read_text("utf-8"))
    previous = {}
    if (data_dir / "manifest.json").is_file():
        previous = {
            s["id"]: s
            for s in json.loads((data_dir / "manifest.json").read_text("utf-8"))["sources"]
        }
    data_dir.parent.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix=f".{data_dir.name}-", dir=data_dir.parent))
    timestamp = _now()
    try:
        sources = []
        with httpx.Client(transport=transport, follow_redirects=True, timeout=60) as client:
            for original in metadata["sources"]:
                source = dict(original)
                if source.get("hf"):
                    revision = previous.get(source["id"], {}).get("revision")
                    if not revision:
                        revision = source.get("revision")
                    if revision == "resolve-at-first-download":
                        response = client.get(
                            "https://huggingface.co/api/datasets/" + source["hf"] + "/revision/main"
                        )
                        response.raise_for_status()
                        revision = response.json()["sha"]
                    if not isinstance(revision, str) or not re.fullmatch(
                        r"[0-9a-fA-F]{40}", revision
                    ):
                        raise ValueError(f"Invalid pinned HF revision for {source['id']}")
                    source["revision"] = revision
                    source["url"] = (
                        "https://huggingface.co/datasets/"
                        + source["hf"]
                        + "/resolve/"
                        + revision
                        + "/"
                        + source["filename"]
                    )
                relative = "raw/" if source["id"] == "tofueval" else source["id"] + "/"
                relative += source["filename"]
                target = stage / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                _fetch(client, dict(source, filename=target.name), target.parent, progress)
                source["local_path"] = relative
                sources.append(source)
        _extract(stage / "raw/tofueval.zip", stage / "repo")
        index = load_split_index(stage / "repo/document_ids_dev_test_split.json")
        duplicates = []
        load_items(stage / "repo", duplicate_records=duplicates)
        transcripts, counts = {}, {}
        for dataset in ("mediasum", "meetingbank"):
            wanted = {doc_id for ds, doc_id in index if ds == dataset}
            if dataset == "mediasum":
                with zipfile.ZipFile(stage / "mediasum/test_data.zip") as zipped:
                    if zipped.namelist().count("test_data.txt") != 1:
                        raise ValueError("Missing or ambiguous MediaSum test_data.txt")
                    with zipped.open("test_data.txt") as stream:
                        selected = _resolve(stream, dataset, wanted)
            else:
                with (stage / "meetingbank/test.json").open("rb") as stream:
                    selected = _resolve(stream, dataset, wanted)
            transcripts.update({f"{dataset}:{key}": value for key, value in selected.items()})
            counts[dataset] = {"wanted": len(wanted), "resolved": len(selected)}
        _json(stage / "derived/transcripts.json", transcripts)
        records = [
            FileRecord(
                path.relative_to(stage).as_posix(),
                path.relative_to(stage).as_posix(),
                _hash_file(path),
                path.stat().st_size,
                timestamp,
            )
            for path in sorted(stage.rglob("*"))
            if path.is_file()
        ]
        by_name = {record.filename: record for record in records}
        for name, expected in metadata.get("expected_sha256", {}).items():
            record = by_name.get(name)
            if record is None or record.sha256 != expected.lower():
                raise ValueError(f"sha256 mismatch for {name!r}")
        _json(
            stage / "manifest.json",
            {
                "sources": sources,
                "files": [asdict(r) for r in records],
                "id_resolution": counts,
                "duplicates": duplicates,
                "timestamp": timestamp,
            },
        )
        manifest = stage / "manifest.json"
        records.append(
            FileRecord(
                "manifest",
                "manifest.json",
                _hash_file(manifest),
                manifest.stat().st_size,
                timestamp,
            )
        )
        # The framework owns this file. Preserve it across our directory promotion.
        if (data_dir / "download.json").is_file():
            shutil.copyfile(data_dir / "download.json", stage / "download.json")
        _promote(stage, data_dir)
        return records
    finally:
        if stage.exists():
            shutil.rmtree(stage)
