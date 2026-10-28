"""Pure-code synthesis: turn the verifier's observations into signals, roles and a verdict."""

import re

from eaudit.atomize.models import AtomicClaim
from eaudit.config import Settings
from eaudit.link.models import LinkResult
from eaudit.models import ConcernType, EvidenceRole, Verdict
from eaudit.prep import Act

from .amounts import compare_amounts, polarity_reversals
from .group_a import GroupA
from .models import (
    CONF_VALUE,
    Concern,
    Decision,
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
_NUMBER_WORDS = (
    r"zero|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|thirteen|fourteen"
    r"|fifteen|sixteen|seventeen|eighteen|nineteen|twenty|thirty|forty|fifty|sixty|seventy"
    r"|eighty|ninety|hundred|thousand|million|billion|dozen|dozens|hundreds|thousands|millions"
    r"|billions|tens|half|halves|couple|pair|single|double(?!-check)|triple|quarter"
)
_NUMBER_TOKEN = re.compile(rf"\d|\b(?:{_NUMBER_WORDS})\b", re.IGNORECASE)

_YEAR = re.compile(r"\b(?:19|20)\d{2}\b")
_PRONOUN_ONE = re.compile(r"\b(?:the|no|any|every|some|that|this|which|each)\s+one\b", re.I)

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
        for k in (f.keys or [it.key for it in items])
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


def _reply_speakers(e, turns: list) -> list[str]:
    """Who said the item's reply turns. A question turn only frames the answer, so its asker is
    left out (unless every turn is a question)."""
    idx = [s.turn_index for s in e.draft.segments if 0 <= s.turn_index < len(turns)]
    replies = [i for i in idx if Act.question not in turns[i].acts] or idx
    return sorted({turns[i].speaker for i in replies if turns[i].speaker is not None})


def _rate_ratio_conflict(
    claim: AtomicClaim, items: list[JudgedEvidence], sig: Signals, ratio: float
) -> None:
    """Bucket 11 in code: two accounts give numeric weekly rates that differ by `ratio` or more.

    "Twice a month" and "once a month" share an ordinal bucket, so the amount check cannot see
    them. Needs a claim that names two or more accounts and items from different speakers.
    """
    if any(f.type == "conflicting_accounts_flattened" for f in sig.flags):
        return
    if len({(r.source, r.speaker) for r in claim.reported_by}) < 2:
        return
    rated: list[tuple[JudgedEvidence, float]] = []
    for it in items:
        o = it.obs
        if o is None or o.relation == "not_addresses" or not it.endorsed or it.demote:
            continue
        rates = [x.rate_per_week for x in o.frequency if x.rate_per_week and x.rate_per_week > 0]
        if rates:
            rated.append((it, rates[0]))
    for n, (a, ra) in enumerate(rated):
        for b, rb in rated[n + 1 :]:
            if a.speakers and b.speakers and set(a.speakers).isdisjoint(b.speakers):
                if max(ra, rb) / min(ra, rb) >= ratio:
                    sig.flags.append(
                        FlagObs(
                            type="conflicting_accounts_flattened", keys=[a.key, b.key], conf="high"
                        )
                    )
                    sig.counts["ratio_conflicts"] = sig.counts.get("ratio_conflicts", 0) + 1
                    return


def has_causal_cue(claim: AtomicClaim) -> bool:
    return bool(_CAUSAL_CUE.search(claim.proposition))


def has_number_token(text: str, turn_side: bool = False) -> bool:
    """A numeral, number word or amount token (currency and percent signs sit next to digits).

    turn_side: also ignore 4-digit years and the pronoun "one" ("the one in Austin", "no one").
    """
    if turn_side:
        text = _PRONOUN_ONE.sub(" ", _YEAR.sub(" ", text))
    return bool(_NUMBER_TOKEN.search(text))


def _quantity_flag_grounded(
    claim: AtomicClaim, keys: list[str], items: list[JudgedEvidence], turns: list
) -> bool:
    """A quantity_mismatch flag needs a figure in the claim and in a cited item's turn text."""
    if not has_number_token(claim.proposition):
        return False
    cited = [it for it in items if not keys or it.key in keys]
    return any(has_number_token(turns[i].text, turn_side=True) for it in cited for i in it.turns)


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
    claim: AtomicClaim,
    items: list[JudgedEvidence],
    flags: list[FlagObs],
    p1: float,
    values: dict[str, float] = CONF_VALUE,
) -> list[str]:
    """Bucket 6: only an unhedged claim against a strongly hedged item; 'probably' is ignored."""
    if claim.hedged:
        return []
    keys = [
        it.key
        for it in items
        if counts_as_support_base(it)
        and it.obs.certainty == "hedged_strong"
        and values[it.obs.conf] >= p1
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
    cfg: Settings | None = None,
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
            speakers=_reply_speakers(e, turns),
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
        kept_keys = [k for k in f.keys if k in known]
        if f.type == "quantity_mismatch" and not _quantity_flag_grounded(
            claim, kept_keys, items, turns
        ):
            sig.counts["flags_suppressed"] = sig.counts.get("flags_suppressed", 0) + 1
            continue
        sig.flags.append(f.model_copy(update={"keys": kept_keys}))
    apply_timeframe(claim, items, sig.flags)
    _rate_ratio_conflict(claim, items, sig, (cfg or Settings()).check_rate_ratio)
    sig.failed_inference = resolve_inferences(link, {it.key: it for it in items}, vout.inferences)
    cited = {
        k
        for f in sig.flags
        if f.type
        in (
            "context_stripping",
            "correction_ignored",
            "unsupported_causal_link",
            "quantity_mismatch",
        )
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
    "quantity_mismatch": ConcernType.quantity_mismatch,
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


# --- roles, decision table, dedup -----------------------------------------------------------

_CHAIN = (
    ConcernType.wrong_attribution,
    ConcernType.negation_reversal,
    ConcernType.frequency_severity_inflation,
    ConcernType.quantity_mismatch,
    ConcernType.contradictory_evidence,
)
_QUANTITY_YIELDS_TO = (
    ConcernType.certainty_inflation,
    ConcernType.correction_ignored,
    ConcernType.conflicting_accounts_flattened,
    ConcernType.timeframe_mismatch,
)
_ORDER = {t: n for n, t in enumerate(ConcernType)}
_Role = EvidenceRole


def _role(it: JudgedEvidence) -> EvidenceRole | None:
    """The role an item plays for the claim; None means nobody cites it (dropped later)."""
    o = it.obs
    if not it.endorsed:
        return _Role.qualifying
    if o is None:
        return None
    if it.escalated:
        return _Role.contradicting
    if it.demote or it.attribution == "mismatch":
        return _Role.qualifying
    if o.relation == "contradicts":
        return _Role.contradicting
    if o.relation == "entails":
        return _Role.qualifying if o.experiencer == "other_person" else _Role.supporting
    return _Role.supporting if it.cited else None  # cited by a flag: partial support


def _merge(concerns: list[Concern]) -> list[Concern]:
    """One concern per type; evidence keys are unioned; 'inflates' wins over 'understates'."""
    merged: dict[ConcernType, Concern] = {}
    for c in concerns:
        m = merged.get(c.type)
        if m is None:
            merged[c.type] = Concern(c.type, list(c.keys), c.direction, c.scale)
            continue
        if m.direction and c.direction and m.direction != c.direction:
            # opposite directions: report the inflating one, with only its own items and scale
            if c.direction == "inflates":
                merged[c.type] = Concern(c.type, list(c.keys), c.direction, c.scale)
            continue
        m.keys = list(dict.fromkeys([*m.keys, *c.keys]))
        if c.scale and m.scale and c.scale != m.scale:
            m.scale = "frequency and severity"
    return list(merged.values())


def dedup(concerns: list[Concern]) -> list[Concern]:
    """Explain once: a specific concern suppresses a more generic one on the same items."""
    cs = {c.type: c for c in _merge(concerns)}
    for n, low in enumerate(_CHAIN):
        for high in _CHAIN[:n]:
            if low in cs and high in cs:
                lc, hc = cs[low], cs[high]
                if not lc.keys or not hc.keys or set(lc.keys) & set(hc.keys):
                    del cs[low]
                    break
    # One discrepancy, one concern: a more specific cause explains an amount gap on the same items.
    qm = cs.get(ConcernType.quantity_mismatch)
    if qm is not None:
        for other in _QUANTITY_YIELDS_TO:
            oc = cs.get(other)
            if oc is not None and (not qm.keys or not oc.keys or set(qm.keys) & set(oc.keys)):
                del cs[ConcernType.quantity_mismatch]
                break
    # D5 precedence: conflicting accounts > correction ignored > generic contradiction
    if ConcernType.conflicting_accounts_flattened in cs:
        cs.pop(ConcernType.correction_ignored, None)
        cs.pop(ConcernType.contradictory_evidence, None)
    if ConcernType.correction_ignored in cs:
        cs.pop(ConcernType.contradictory_evidence, None)
    if any(t != ConcernType.unsupported_claim for t in cs):
        cs.pop(ConcernType.unsupported_claim, None)
    return sorted(cs.values(), key=lambda c: _ORDER[c.type])


def _candidates(
    claim: AtomicClaim, items: list[JudgedEvidence], sig: Signals, cfg: Settings
) -> list[Concern]:
    out: list[Concern] = []
    base = [it for it in items if counts_as_support_base(it)]
    # Experiencer: the behaviour is described, but about someone else.
    other = [
        it.key
        for it in items
        if it.obs is not None
        and it.obs.relation in ("entails", "contradicts")
        and it.obs.experiencer == "other_person"
        and it.endorsed
        and not it.demote
    ]
    if other:
        out.append(Concern(ConcernType.wrong_attribution, other))
    # Reporter: the content is there, but only from speakers the claim does not name.
    mism = [
        it.key
        for it in items
        if it.attribution == "mismatch"
        and it.endorsed
        and it.obs is not None
        and it.obs.relation == "entails"
        and it.obs.experiencer != "other_person"
    ]
    if mism and not base:
        out.append(Concern(ConcernType.wrong_attribution, mism))
    contra = [it for it in items if _role(it) == _Role.contradicting and not it.escalated]
    rev = polarity_reversals(claim, contra)
    if rev:
        out.append(Concern(ConcernType.negation_reversal, rev))
    if contra:
        out.append(Concern(ConcernType.contradictory_evidence, [it.key for it in contra]))
    flagged = {f.type for f in sig.flags}
    if "conflicting_accounts_flattened" not in flagged:
        by_key = {it.key: it for it in items}
        for f in compare_amounts(claim, base, cfg):
            if f.escalate:
                by_key[f.key].escalated = True
            out.append(
                Concern(ConcernType.frequency_severity_inflation, [f.key], f.direction, f.kind)
            )
    ck = certainty_keys(claim, items, sig.flags, cfg.check_min_conf_p1, cfg.check_conf_values)
    if ck:
        out.append(Concern(ConcernType.certainty_inflation, ck))
    out += flag_concerns(items, sig.flags)
    return out


def decide(
    claim: AtomicClaim, judged: list[JudgedEvidence], signals: Signals, cfg: Settings
) -> Decision:
    """Pure: observations in, verdict + concerns + evidence roles out (decision table D0-D9)."""
    if claim.scope != "in_scope":
        return Decision(Verdict.out_of_scope, row="D0")
    if not judged:
        return Decision(
            Verdict.insufficient_evidence, [Concern(ConcernType.unsupported_claim)], row="D2"
        )
    cands = _candidates(claim, judged, signals, cfg)  # may escalate items to contradicting
    roles = {it.key: _role(it) for it in judged}
    sup = [k for k, r in roles.items() if r == _Role.supporting]
    con = [k for k, r in roles.items() if r == _Role.contradicting]
    tf_keys = [it.key for it in judged if it.demote == "timeframe"]
    inf_keys = [it.key for it in judged if it.demote == "inference"]
    if con and not any(c.type == ConcernType.contradictory_evidence for c in cands):
        cands.append(Concern(ConcernType.contradictory_evidence, con))
    if con and not sup:
        row, verdict = "D4", Verdict.contradicted
        kept = [c for c in cands if c.type in _CHAIN]
    elif con:
        row, verdict = "D5", Verdict.partially_supported
        kept = cands
    elif not sup:
        row = "D6" if _has_demoted(judged) else "D7"
        verdict = Verdict.insufficient_evidence
        kept = [c for c in cands if c.type == ConcernType.wrong_attribution]
        if tf_keys:
            kept.append(Concern(ConcernType.timeframe_mismatch, tf_keys))
        if inf_keys:
            kept.append(Concern(ConcernType.unsupported_claim, inf_keys))
        if not kept:
            kept = [Concern(ConcernType.unsupported_claim)]
    else:
        kept = [
            c
            for c in cands
            if c.type not in (ConcernType.contradictory_evidence, ConcernType.timeframe_mismatch)
        ]
        row, verdict = ("D8", Verdict.partially_supported) if kept else ("D9", Verdict.supported)
    concerns = dedup(kept)
    return _finish(judged, roles, concerns, verdict, row)


def _has_demoted(judged: list[JudgedEvidence]) -> bool:
    return any(
        it.demote
        or it.attribution == "mismatch"
        or (it.obs and it.obs.experiencer == "other_person")
        for it in judged
        if it.obs is not None and it.obs.relation != "not_addresses"
    )


def _finish(judged, roles, concerns, verdict, row) -> Decision:
    out: dict[str, EvidenceRole] = {}
    counts: dict[str, int] = {}
    cited = {k for c in concerns for k in c.keys}
    for it in judged:
        r = roles[it.key]
        if r is None and it.key in cited:
            r = _Role.qualifying  # cited by a concern but not entailing
        if r is None:
            counts["items_dropped"] = counts.get("items_dropped", 0) + 1
            continue
        if r != it.linked.draft.role:
            counts["role_disagreements"] = counts.get("role_disagreements", 0) + 1
        out[it.key] = r
    for c in concerns:
        c.keys = [k for k in c.keys if k in out]
    return Decision(verdict, concerns, out, row, counts)
