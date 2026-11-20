"""Per-character normalization with an index map back to the original string."""

import unicodedata

_ZERO_WIDTH = {"​", "‌", "‍", "⁠", "﻿", "­"}
_PUNCT = str.maketrans(
    {
        "‘": "'",
        "’": "'",
        "‚": "'",
        "‛": "'",
        "“": '"',
        "”": '"',
        "„": '"',
        "‟": '"',
        "‐": "-",
        "‑": "-",
        "‒": "-",
        "–": "-",
        "—": "-",
        "−": "-",
    }
)


def normalize(text: str) -> tuple[str, list[int]]:
    """Return (normalized, index_map).

    index_map[i] is the original code-point index of the source char that produced normalized
    char i. A whitespace run maps to the index of its first char. A hit [a, b) in the normalized
    string maps back to [index_map[a], index_map[b-1] + 1) in the original.
    """
    out: list[str] = []
    imap: list[int] = []
    prev_space = False
    for i, ch in enumerate(text):
        if ch in _ZERO_WIDTH:
            continue
        for c in unicodedata.normalize("NFKC", ch).casefold().translate(_PUNCT):
            if c in _ZERO_WIDTH:
                continue
            if c.isspace():
                if prev_space:
                    continue
                out.append(" ")
                imap.append(i)
                prev_space = True
            else:
                out.append(c)
                imap.append(i)
                prev_space = False
    return "".join(out), imap
