"""Build faithful turns from the local, turns-ready transcript records."""

from __future__ import annotations

import json
import re
from collections.abc import Sequence
from copy import deepcopy
from functools import cache
from pathlib import Path
from typing import Any


def build_mediasum_turns(
    speakers: Sequence[str], utterances: Sequence[str],
) -> list[dict[str, str]]:
    """Keep every supplied label and utterance verbatim, including repeated labels."""
    if len(speakers) != len(utterances):
        raise ValueError("MediaSum speaker/utterance lengths differ")
    if not all(speaker.strip() for speaker in speakers):
        raise ValueError("MediaSum has an empty speaker")
    return [
        {"id": f"t{index}", "speaker": speaker, "text": text}
        for index, (speaker, text) in enumerate(zip(speakers, utterances, strict=True))
    ]


def build_meetingbank_turns(blob: str) -> list[dict[str, str]]:
    """Collapse whitespace and greedily pack whole sentences up to 60 words.

    An over-long sentence remains alone. No speaker identity is supplied by this
    source, so all turns use the explicit placeholder ``unlabeled``.
    """
    chunks: list[str] = []
    pending: list[str] = []
    word_count = 0
    for sentence in re.split(r"(?<=[.!?])\s+", blob.strip()):
        words = sentence.split()
        if not words:
            continue
        if pending and word_count + len(words) > 60:
            chunks.append(" ".join(pending))
            pending, word_count = [], 0
        pending.append(" ".join(words))
        word_count += len(words)
    if pending:
        chunks.append(" ".join(pending))
    return [
        {"id": f"t{index}", "speaker": "unlabeled", "text": chunk}
        for index, chunk in enumerate(chunks)
    ]


class TranscriptCache:
    """Lazily read one derived file and memoise turns by dataset/document.

    The file maps ``mediasum:<raw_doc_id>`` to ``{speaker: [...], utt: [...]}``
    and ``meetingbank:<raw_doc_id>`` to ``{transcript: ...}``. Returned turns are
    independent copies, so one request cannot mutate another request's evidence.
    A cache represents a source snapshot; create a fresh cache after downloads.
    """

    def __init__(self, path: Path):
        self.path = Path(path)
        self._records: dict[str, Any] | None = None
        self._turns: dict[tuple[str, str], list[dict[str, str]]] = {}

    def turns(self, dataset: str, doc_id: str) -> list[dict[str, str]]:
        """Return the document's turns; missing document keys fail loudly."""
        if dataset not in {"mediasum", "meetingbank"}:
            raise ValueError(f"Unknown transcript dataset {dataset!r}")
        key = (dataset, doc_id)
        if key not in self._turns:
            if self._records is None:
                self._records = json.loads(self.path.read_text(encoding="utf-8"))
            record = self._records[f"{dataset}:{doc_id}"]
            self._turns[key] = (
                build_mediasum_turns(record["speaker"], record["utt"])
                if dataset == "mediasum"
                else build_meetingbank_turns(record["transcript"])
            )
        return deepcopy(self._turns[key])


@cache
def _cache_for_path(path: Path) -> TranscriptCache:
    return TranscriptCache(path)


def get_transcript_turns(data_dir: Path, dataset: str, doc_id: str) -> list[dict[str, str]]:
    """Use the process-wide lazy cache for a local dataset directory.

    Cache identity is the resolved derived-file path, allowing independent local
    data directories. An adapter refreshing data can instead own a fresh
    ``TranscriptCache`` for its new snapshot.
    """
    path = (Path(data_dir) / "derived/transcripts.json").resolve()
    return _cache_for_path(path).turns(dataset, doc_id)


def invalidate_transcripts(data_dir: Path) -> None:
    """Discard a refreshed directory's process snapshot without evicting others."""
    path = (Path(data_dir) / "derived/transcripts.json").resolve()
    snapshot = _cache_for_path(path)
    snapshot._records = None
    snapshot._turns.clear()
