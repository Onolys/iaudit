"""Ordinal frequency and severity scales shared by 03 (extract) and 05 (compare)."""

import re
from dataclasses import dataclass
from enum import IntEnum
from typing import Literal

Kind = Literal["frequency", "severity"]


class FrequencyBucket(IntEnum):
    never = 0
    rarely = 1  # below about monthly, < 0.2/wk
    sometimes = 2  # monthly up to weekly, 0.2 to < 1/wk
    often = 3  # 1 to < 4/wk
    most = 4  # 4 to < 7/wk, "most days", "usually"
    always = 5  # daily or more, "every time", "constantly"


class SeverityBucket(IntEnum):
    none = 0
    mild = 1
    moderate = 2
    severe = 3
    inability = 4


_WEEKS_PER_MONTH = 52 / 12
_PER_WEEK = {"day": 7.0, "week": 1.0, "month": 1 / _WEEKS_PER_MONTH, "year": 1 / 52}
_WORDS = {
    **{w: float(i) for i, w in enumerate(
        "zero one two three four five six seven eight nine ten eleven twelve".split()
    )},
    "once": 1.0,
    "twice": 2.0,
    "thrice": 3.0,
}  # fmt: skip
_COUNT = r"(?:\d+(?:\.\d+)?|" + "|".join(sorted(_WORDS, key=len, reverse=True)) + r")"
_COUNT_RATE = re.compile(
    rf"\b(?P<a>{_COUNT})(?:\s*(?:-|–|to|or)\s*(?P<b>{_COUNT}))?\s*(?:times?|x)?\s*"
    r"(?:a|an|per|each|every|/)\s*(?P<p>day|week|month|year)\b"
)
_EVERY = re.compile(r"\b(?:every|each)\s+(?P<p>day|week|month|year)\b")
_ADVERB = {"daily": "day", "weekly": "week", "monthly": "month", "yearly": "year"}


def _num(s: str) -> float:
    return _WORDS[s] if s in _WORDS else float(s)


def _clean(text: str) -> str:
    return text.lower().replace("’", "'")


def parse_rate(text: str) -> float | None:
    """Numeric frequency text -> times per week (range = midpoint); None if not numeric."""
    t = _clean(text)
    m = _COUNT_RATE.search(t)
    if m:
        lo = _num(m["a"])
        hi = _num(m["b"]) if m["b"] else lo
        return (lo + hi) / 2 * _PER_WEEK[m["p"]]
    m = _EVERY.search(t)
    if m:
        return _PER_WEEK[m["p"]]
    for adv, period in _ADVERB.items():
        if re.search(rf"\b{adv}\b", t):
            return _PER_WEEK[period]
    return None


def bucket_from_rate(rate_per_week: float) -> FrequencyBucket:
    r = rate_per_week
    if r <= 0:
        return FrequencyBucket.never
    if r < 0.2:
        return FrequencyBucket.rarely
    if r < 1:
        return FrequencyBucket.sometimes
    if r < 4:
        return FrequencyBucket.often
    if r < 7:
        return FrequencyBucket.most
    return FrequencyBucket.always


_FREQ_LEXICON: list[tuple[str, FrequencyBucket]] = [
    (r"never|not once", FrequencyBucket.never),
    (r"rarely|seldom|hardly ever|almost never|once in a while", FrequencyBucket.rarely),
    (r"sometimes|occasionally|now and then|from time to time", FrequencyBucket.sometimes),
    (
        r"often|frequently|regularly|(?:several|a few|a couple of) times a week",
        FrequencyBucket.often,
    ),
    (
        r"most (?:days|times|meetings|nights|mornings|evenings|weeks)|most of the time"
        r"|usually|typically",
        FrequencyBucket.most,
    ),
    (
        r"always|every time|every day|daily|constantly|every (?:single )?\w+ meeting"
        r"|every meeting|all the time|each time|several times a day|continuously|nonstop",
        FrequencyBucket.always,
    ),
]
_SEV_LEXICON: list[tuple[str, SeverityBucket]] = [
    (r"no difficulty|no trouble|none|no problem", SeverityBucket.none),
    (r"slight|a little|a bit|mild|minor|some difficulty|some trouble", SeverityBucket.mild),
    (r"moderate|fair|considerable", SeverityBucket.moderate),
    (r"poor|marked|significant|a lot|severe|serious|major|substantial", SeverityBucket.severe),
    (r"unable|can't|cannot|not able|incapable|completely", SeverityBucket.inability),
]


def lexicon_bucket(text: str, kind: Kind) -> IntEnum | None:
    """Relative-word lookup; the longest matched phrase wins."""
    t = _clean(text)
    table = _FREQ_LEXICON if kind == "frequency" else _SEV_LEXICON
    best: tuple[int, int, IntEnum] | None = None
    for pattern, bucket in table:
        for m in re.finditer(rf"(?<![\w'])(?:{pattern})(?![\w'])", t):
            cand = (len(m.group()), -m.start(), bucket)
            if best is None or cand[:2] > best[:2]:
                best = cand
    return best[2] if best else None


@dataclass(frozen=True)
class ResolvedQuantity:
    bucket: IntEnum | None
    rate_per_week: float | None = None


def resolve_quantity(kind: Kind, raw: str, llm_bucket: IntEnum | None) -> ResolvedQuantity:
    """Code wins over the LLM: numeric text -> rate -> bucket, else lexicon, else LLM bucket."""
    if kind == "frequency":
        rate = parse_rate(raw)
        if rate is not None:
            return ResolvedQuantity(bucket_from_rate(rate), rate)
    lex = lexicon_bucket(raw, kind)
    return ResolvedQuantity(lex if lex is not None else llm_bucket, None)


def step_diff(claim: IntEnum, evidence: IntEnum) -> int:
    """Signed steps between buckets of one scale. Positive = claim stronger than evidence."""
    if type(claim) is not type(evidence):
        raise TypeError("step_diff compares buckets of the same scale")
    return int(claim) - int(evidence)
