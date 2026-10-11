"""Pure-code synthesis: turn the verifier's observations into signals, roles and a verdict."""

import re

from iaudit_backend.atomize.models import AtomicClaim
from iaudit_backend.link.models import LinkResult
from iaudit_backend.models import ConcernType

from .group_a import GroupA
from .models import (
    CONF_VALUE,
    Concern,
    FlagObs,
    InferenceObs,
    JudgedEvidence,
    Signals,
    VerifierOutput,
)

_NON_ENDORSED = ("question_only", "non_answer")
_CAUSAL_CUE = re.compile(
    r"\b(?:because|caus(?:e|es|ed|ing)|due to|led to|leads to|resulted in|results in"
    r"|so|therefore)\b",
    re.IGNORECASE,
)

# --- timeframe (bucket 4) -------------------------------------------------------------------


def timeframe_mismatch(claim_tf: str, item_tf: str) -> bool:
    if claim_tf == "unspecified" or item_tf == "unspecified":
        return False
    if item_tf == "hypothetical":
        return claim_tf != "hypothetical"
    if claim_tf in ("current", "future"):
        return item_tf in ("past", "childhood")
    if claim_tf in ("past", "childhood"):
        return item_tf == "current"
    return False


def apply_timeframe(claim: AtomicClaim, items: list[JudgedEvidence], flags: list[FlagObs]) -> int:
    """Demote items from the wrong period: they no longer count as support or contradiction.

    An implicit-current claim (the text never states a time) only fires at high confidence.
    Returns the number of demoted items.
    """
    implicit = claim.timeframe == "current" and not claim.timeframe_explicit
    flagged = {
        k
        for f in flags
        if f.type == "timeframe_mismatch" and (not implicit or f.conf == "high")
        for k in f.keys
    }
    n = 0
    for it in items:
        o = it.obs
        if o is None or o.relation == "not_addresses" or it.demote:
            continue
        hit = timeframe_mismatch(claim.timeframe, o.timeframe) and (
            not implicit or o.conf == "high"
        )
        if hit or it.key in flagged:
            it.demote = "timeframe"
            n += 1
    return n


# --- certainty, flags, causal cue, inference --------------------------------------------------


def has_causal_cue(claim: AtomicClaim) -> bool:
    return bool(_CAUSAL_CUE.search(claim.proposition))


def counts_as_support_base(it: JudgedEvidence) -> bool:
    """An item the claim can lean on: judged as entailing, in period, from its accounts."""
    o = it.obs
    return (
        o is not None
        and o.relation == "entails"
        and it.endorsed
        and not it.demote
        and it.attribution != "mismatch"
        and o.experiencer != "other_person"
    )


def certainty_keys(
    claim: AtomicClaim, items: list[JudgedEvidence], flags: list[FlagObs], p1: float
) -> list[str]:
    """Bucket 6: only an unhedged claim against a strongly hedged item; 'probably' is ignored."""
    if claim.hedged:
        return []
    keys = [
        it.key
        for it in items
        if counts_as_support_base(it)
        and it.obs.certainty == "hedged_strong"
        and CONF_VALUE[it.obs.conf] >= p1
    ]
    for f in flags:
        if f.type == "certainty_inflation":
            keys += f.keys or [it.key for it in items if counts_as_support_base(it)]
    return list(dict.fromkeys(keys))


def resolve_inferences(
    link: LinkResult,
    by_key: dict[str, JudgedEvidence],
    judgments: list[InferenceObs],
) -> bool:
    """An inference is supported iff every premise entails and the step is acceptable.

    Premises of failed groups are demoted (they supply no support). Returns True if any failed.
    """
    verdict = {g.key: g.step_acceptable for g in judgments}
    supported_premises: set[str] = set()
    failed: list[list[str]] = []
    for e in link.evidence:
        if e.link_type != "inference":
            continue
        prem = [by_key.get(k) for k in e.premise_keys]
        ok = (
            bool(prem)
            and verdict.get(e.draft.key, False)
            and all(
                p is not None and p.obs is not None and p.obs.relation == "entails" for p in prem
            )
        )
        keys = [k for k in e.premise_keys if k in by_key]
        if ok:
            supported_premises.update(keys)
        else:
            failed.append(keys)
    for keys in failed:
        for k in keys:
            if k not in supported_premises:
                by_key[k].demote = by_key[k].demote or "inference"
    return bool(failed)


def judge(
    claim: AtomicClaim,
    link: LinkResult,
    ga: GroupA,
    turns: list,
    vout: VerifierOutput,
    counts: dict[str, int] | None = None,
) -> tuple[list[JudgedEvidence], Signals]:
    """Join the link items, group A results and floored observations; run the per-item checks."""
    sig = Signals(counts=dict(counts or {}))
    obs = {i.key: i for i in vout.items}
    items = [
        JudgedEvidence(
            key=e.draft.key,
            linked=e,
            obs=obs.get(e.draft.key),
            turns=[s.turn_index for s in e.draft.segments if 0 <= s.turn_index < len(turns)],
            endorsed=e.answer_status not in _NON_ENDORSED,
            attribution=ga.attribution.get(e.draft.key, "ok"),
        )
        for e in link.evidence
        if e.link_type != "inference"
    ]
    known = {it.key for it in items}
    for f in vout.flags:
        if f.type == "unsupported_causal_link" and not has_causal_cue(claim):
            sig.counts["flags_suppressed"] = sig.counts.get("flags_suppressed", 0) + 1
            continue
        sig.flags.append(f.model_copy(update={"keys": [k for k in f.keys if k in known]}))
    apply_timeframe(claim, items, sig.flags)
    sig.failed_inference = resolve_inferences(link, {it.key: it for it in items}, vout.inferences)
    cited = {
        k
        for f in sig.flags
        if f.type in ("context_stripping", "correction_ignored", "unsupported_causal_link")
        for k in f.keys
    }
    for it in items:
        it.cited = it.key in cited
    return items, sig


_FLAG_CONCERN = {
    "context_stripping": ConcernType.context_stripping,
    "correction_ignored": ConcernType.correction_ignored,
    "conflicting_accounts_flattened": ConcernType.conflicting_accounts_flattened,
    "unsupported_causal_link": ConcernType.unsupported_causal_link,
    "element_gap": ConcernType.unsupported_claim,
}


def flag_concerns(items: list[JudgedEvidence], flags: list[FlagObs]) -> list[Concern]:
    """Concerns from accepted flags. A flag with no keys rests on the items the claim leans on."""
    base = [it.key for it in items if counts_as_support_base(it) or it.cited]
    out = []
    for f in flags:
        ctype = _FLAG_CONCERN.get(f.type)
        if ctype is not None:
            out.append(Concern(ctype, list(f.keys) or base))
    return out
