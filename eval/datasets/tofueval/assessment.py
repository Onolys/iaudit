"""Join summary sentences without exposing gold annotations in the assessment."""

from collections.abc import Iterable, Mapping
from copy import deepcopy
from typing import Any


def assert_sentence_offsets(text: str, sentences: Iterable[Mapping[str, Any]]) -> None:
    """Fail loudly if a sentence's code-point span no longer identifies its text."""
    for sentence in sentences:
        start, end = sentence["start"], sentence["end"]
        assert 0 <= start <= end <= len(text) and text[start:end] == sentence["text"], (
            f"Sentence {sentence['sent_idx']} has invalid assessment offsets [{start}:{end}]"
        )


def build_assessment(
    sentences: Iterable[Mapping[str, Any]],
) -> tuple[dict[str, str], list[dict[str, Any]]]:
    """Return a request section and independent, ordered payload sentences.

    Callers supply normalized payload fields ``sent_idx`` and verbatim ``text``;
    all other fields (including gold metadata) remain only in the copied payload.
    Item loading owns grouping and duplicate resolution. Missing indices require
    no placeholders: only present sentences contribute text and offsets.
    """
    positioned = [deepcopy(dict(sentence)) for sentence in sentences]
    for sentence in positioned:
        sentence["sent_idx"] = int(sentence["sent_idx"])
    positioned.sort(key=lambda sentence: sentence["sent_idx"])

    text = " ".join(sentence["text"] for sentence in positioned)
    cursor = 0
    for sentence in positioned:
        sentence["start"] = cursor
        sentence["end"] = cursor + len(sentence["text"])
        cursor = sentence["end"] + 1
    assert_sentence_offsets(text, positioned)
    return {"id": "s0", "text": text}, positioned
