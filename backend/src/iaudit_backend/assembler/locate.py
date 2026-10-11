"""The single offset-resolution function: exact, normalized, guarded fuzzy, ellipsis, hint."""

import re
from collections import Counter
from dataclasses import dataclass

from rapidfuzz import fuzz

from iaudit_backend.config import Settings

from .normalize import normalize

_TIER_RANK = {"exact": 0, "normalized": 1, "fuzzy": 2}
_ELLIPSIS = re.compile(r"\[\s*(?:\.{3,}|…)\s*\]|\.{3,}|…")
_TOKEN = re.compile(r"\w+(?:'\w+)*")
_NUMBER_WORDS = frozenset(
    "zero one two three four five six seven eight nine ten eleven twelve once twice thrice "
    "daily weekly monthly yearly hourly nightly".split()
)
_NEGATORS = frozenset("no not never none nobody nothing neither nor without cannot".split())
_WINDOW_MIN, _WINDOW_MAX = 0.8, 1.25
_HULL_MAX = 2.5


@dataclass(frozen=True)
class Match:
    start: int
    end: int
    tier: str
    score: float
    occurrences: int = 1


def _pick(starts: list[int], hint: int | None) -> int:
    if hint is None or len(starts) == 1:
        return starts[0]
    return min(starts, key=lambda s: (abs(s - hint), s))


def _trim(text: str, start: int, end: int) -> tuple[int, int] | None:
    while start < end and text[start].isspace():
        start += 1
    while end > start and text[end - 1].isspace():
        end -= 1
    return (start, end) if end > start else None


def _find_all(hay: str, needle: str) -> list[int]:
    out, i = [], hay.find(needle)
    while i != -1:
        out.append(i)
        i = hay.find(needle, i + 1)
    return out


def _guard_tokens(s: str) -> Counter:
    c: Counter = Counter()
    for tok in _TOKEN.findall(s):
        if (
            any(ch.isdigit() for ch in tok)
            or tok in _NUMBER_WORDS
            or tok in _NEGATORS
            or tok.endswith("n't")
        ):
            c[tok] += 1
    return c


def _locate_one(text: str, needle: str, hint: int | None, cfg: Settings) -> Match | None:
    stripped = needle.strip()
    if not stripped:
        return None
    # Tier 1: exact
    starts = _find_all(text, stripped)
    if starts:
        s = _pick(starts, hint)
        return Match(s, s + len(stripped), "exact", 100.0, len(starts))
    # Tier 2: normalized
    ntext, imap = normalize(text)
    nneedle, _ = normalize(stripped)
    nneedle = nneedle.strip()
    if not nneedle:
        return None
    starts = _find_all(ntext, nneedle)
    if starts:
        if hint is None:
            a = starts[0]
        else:
            a = min(starts, key=lambda x: (abs(imap[x] - hint), x))
        t = _trim(text, imap[a], imap[a + len(nneedle) - 1] + 1)
        if t:
            return Match(t[0], t[1], "normalized", 100.0, len(starts))
        return None
    # Tier 3: guarded fuzzy
    if len(nneedle) < cfg.fuzzy_min_len or len(nneedle) > len(ntext):
        return None
    al = fuzz.partial_ratio_alignment(nneedle, ntext, score_cutoff=cfg.fuzzy_threshold)
    if al is None or al.score < cfg.fuzzy_threshold:
        return None
    ds, de = al.dest_start, al.dest_end
    while 0 < ds < len(ntext) and ntext[ds - 1].isalnum() and ntext[ds].isalnum():
        ds -= 1
    while 0 < de < len(ntext) and ntext[de - 1].isalnum() and ntext[de].isalnum():
        de += 1
    window = ntext[ds:de].strip()
    if not window:
        return None
    ratio = len(window) / len(nneedle)
    if not _WINDOW_MIN <= ratio <= _WINDOW_MAX:
        return None
    if _guard_tokens(nneedle) != _guard_tokens(window):
        return None
    lead = len(ntext[ds:de]) - len(ntext[ds:de].lstrip())
    a, b = ds + lead, ds + lead + len(window)
    t = _trim(text, imap[a], imap[b - 1] + 1)
    if not t:
        return None
    return Match(t[0], t[1], "fuzzy", float(al.score))


def locate(text: str, needle: str, hint: int | None, cfg: Settings) -> Match | None:
    """Find `needle` in `text`. Offsets are code points in `text` exactly as received."""
    if not _ELLIPSIS.search(needle):
        return _locate_one(text, needle, hint, cfg)
    frags = [f.strip() for f in _ELLIPSIS.split(needle) if f.strip()]
    if not frags:
        return None
    pos, matches = 0, []
    for f in frags:
        m = _locate_one(text[pos:], f, None if hint is None else hint - pos, cfg)
        if m is None:
            return None
        matches.append(Match(m.start + pos, m.end + pos, m.tier, m.score, m.occurrences))
        pos = matches[-1].end
    start, end = matches[0].start, matches[-1].end
    if len(matches) > 1 and (end - start) > _HULL_MAX * sum(len(f) for f in frags):
        return None
    tier = max((m.tier for m in matches), key=_TIER_RANK.__getitem__)
    return Match(start, end, tier, min(m.score for m in matches), matches[0].occurrences)
