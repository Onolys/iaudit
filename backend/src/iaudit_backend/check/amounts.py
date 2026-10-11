"""Buckets 2, 5 and 7 decided in code: polarity and ordinal amount comparison, both directions."""

import re
from dataclasses import dataclass
from enum import IntEnum
from typing import Literal

from iaudit_backend.atomize.models import AtomicClaim
from iaudit_backend.config import Settings
from iaudit_backend.scales import (
    FrequencyBucket,
    Kind,
    SeverityBucket,
    bucket_from_rate,
    lexicon_bucket,
    resolve_quantity,
    step_diff,
)

from .models import JudgedEvidence, QuantityObs

# Lower-bound cues: vague quantifiers compatible with a higher rate. "some", "mild" and
# "a little" are level words, not cues. A negator just before a cue ("not often") cancels it.
AT_LEAST_CUES = (
    "repeatedly", "frequently", "regularly", "often", "several", "many", "multiple",
    "at least", "more than", "a number of", "numerous", "a lot", "lots of", "again and again",
    "over and over", "time and again",
)  # fmt: skip
_CUE = re.compile(r"\b(?:" + "|".join(AT_LEAST_CUES) + r")\b", re.IGNORECASE)
_NEGATED = re.compile(
    r"\b(?:not|never|no|hardly|rarely|barely|seldom|scarcely)\b(?:\W+\w+){0,2}\W*$", re.IGNORECASE
)
_BOUNDS = (0.2, 1.0, 4.0, 7.0)  # weekly rates where frequency buckets change
_NEAR = 0.15
_BUCKETS: dict[str, type[IntEnum]] = {"frequency": FrequencyBucket, "severity": SeverityBucket}

Basis = Literal["numeric", "relative", "model"]


@dataclass(frozen=True)
class Value:
    bucket: IntEnum
    basis: Basis
    raw: str = ""
    rate: float | None = None


@dataclass
class AmountFinding:
    kind: Kind
    direction: Literal["inflates", "understates"]
    key: str  # the compared evidence item
    escalate: bool = False  # evidence says none/never, or the gap is large: a contradiction


def has_at_least_cue(raw: str) -> bool:
    return any(not _NEGATED.search(raw[: m.start()]) for m in _CUE.finditer(raw))


def claim_values(claim: AtomicClaim, kind: Kind) -> list[Value]:
    out = []
    for q in claim.quantities:
        if q.kind != kind:
            continue
        llm = _BUCKETS[kind][q.bucket] if q.bucket in _BUCKETS[kind].__members__ else None
        if kind == "frequency" and q.rate_per_week is not None:
            res_bucket, rate = bucket_from_rate(q.rate_per_week), q.rate_per_week
        else:
            r = resolve_quantity(kind, q.raw, llm)
            res_bucket, rate = r.bucket, r.rate_per_week
        if res_bucket is None:
            continue
        out.append(Value(res_bucket, "numeric" if rate is not None else "relative", q.raw, rate))
    return out


def evidence_value(kind: Kind, o: QuantityObs) -> Value | None:
    """rate_per_week -> bucket, else the lexicon, else the model's guess (basis 'model')."""
    if kind == "frequency" and o.rate_per_week is not None:
        return Value(bucket_from_rate(o.rate_per_week), "numeric", o.raw, o.rate_per_week)
    lex = lexicon_bucket(o.raw, kind) if o.raw else None
    if lex is not None:
        return Value(lex, "numeric" if o.basis == "numeric" else "relative", o.raw)
    if o.bucket_guess in _BUCKETS[kind].__members__:
        return Value(_BUCKETS[kind][o.bucket_guess], "model", o.raw)
    return None


def _near_boundary(rate: float | None) -> bool:
    return rate is not None and any(abs(rate - b) <= _NEAR * b for b in _BOUNDS)


def compare_kind(
    claim: AtomicClaim, items: list[JudgedEvidence], kind: Kind, cfg: Settings
) -> AmountFinding | None:
    """Compare claim amounts of one kind with the entailing items' amounts."""
    cvals = claim_values(claim, kind)
    if not cvals:
        return None
    pairs: list[tuple[bool, int, Value, Value, str]] = []
    for it in items:
        if it.obs is None:
            continue
        obs = it.obs.frequency if kind == "frequency" else it.obs.severity
        for o in obs:
            ev = evidence_value(kind, o)
            if ev is None:
                continue
            for cv in cvals:
                d = step_diff(cv.bucket, ev.bucket)
                pairs.append((cv.basis == ev.basis, d, cv, ev, it.key))
    if not pairs:
        return None
    same = [p for p in pairs if p[0]]
    pool = same or pairs  # same-basis first; mixed only when no same-basis pair exists
    same_basis, d, cv, ev, key = min(pool, key=lambda p: abs(p[1]))
    if d == 0 or abs(d) < cfg.check_step_material:
        return None
    if abs(d) == 1 and (not same_basis or _near_boundary(ev.rate)):
        return None  # adjacent and ambiguous: benefit of the doubt
    if d < 0:
        if has_at_least_cue(cv.raw):
            return None  # a vague quantifier is compatible with a higher rate
        return AmountFinding(kind, "understates", key)
    escalate = (int(ev.bucket) == 0 and int(cv.bucket) >= 1) or d >= cfg.check_contradict_gap
    return AmountFinding(kind, "inflates", key, escalate)


def compare_amounts(
    claim: AtomicClaim, items: list[JudgedEvidence], cfg: Settings
) -> list[AmountFinding]:
    kinds: tuple[Kind, ...] = ("frequency", "severity")
    return [f for k in kinds if (f := compare_kind(claim, items, k, cfg))]


def polarity_reversals(claim: AtomicClaim, items: list[JudgedEvidence]) -> list[str]:
    """Keys of contradicting items about the claim subject whose polarity is the reverse."""
    out = []
    for it in items:
        o = it.obs
        if o is None or o.relation != "contradicts" or o.experiencer != "claim_subject":
            continue
        if o.polarity in ("affirmed", "negated") and o.polarity != claim.polarity:
            out.append(it.key)
    return out
