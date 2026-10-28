"""R4: deterministic validation of the linker output, per claim. Offsets stay 02's job."""

from collections import Counter
from dataclasses import dataclass, field

from eaudit.assembler.locate import locate
from eaudit.assembler.models import EvidenceDraft, ExcerptSegment
from eaudit.config import Settings
from eaudit.models import EvidenceRole, Turn
from eaudit.prep import Act, PrepResult

from .models import LinkedEvidence, LinkerItem, LinkerOutput

SHORT_REPLY_CHARS = 80
_ADVERSE_FIRST = {
    EvidenceRole.contradicting: 0,
    EvidenceRole.qualifying: 1,
    EvidenceRole.supporting: 2,
}


@dataclass
class Validated:
    evidence: list[LinkedEvidence] = field(default_factory=list)
    ambiguous_turns: list[int] = field(default_factory=list)
    counts: Counter = field(default_factory=Counter)


@dataclass
class _Plain:
    item: LinkerItem
    segs: list[tuple[int, str]]
    role: EvidenceRole
    status: str = "n/a"


def _snap(segs: list[tuple[int, str]], turns: list[Turn], prep: PrepResult, counts: Counter):
    """Make Q+reply segments end/start at turn edges so 02's cross-turn merge rule holds."""
    if len(segs) < 2:
        return segs
    out = []
    for n, (t, text) in enumerate(segs):
        is_q = Act.question in prep.turns[t].acts
        has_next = n + 1 < len(segs) and segs[n + 1][0] == t + 1
        after_q = (
            n > 0 and segs[n - 1][0] == t - 1 and Act.question in prep.turns[segs[n - 1][0]].acts
        )
        full = turns[t].text
        if (is_q and has_next) or (after_q and len(full) <= SHORT_REPLY_CHARS):
            if text != full:
                counts["snapped"] += 1
            text = full
        out.append((t, text))
    return out


def answer_status(turn_ids: list[int], prep: PrepResult) -> str:
    ts = [prep.turns[t] for t in turn_ids]
    qs = [t for t in ts if Act.question in t.acts]
    answers = [
        t
        for t in ts
        if Act.answer in t.acts
        and Act.backchannel not in t.acts
        and any(t.speaker != q.speaker for q in qs)
    ]
    if qs and answers:
        return "endorsed"
    if qs and any(Act.backchannel in t.acts for t in ts):
        return "non_answer"
    if ts and all(Act.question in t.acts for t in ts):
        return "question_only"
    return "n/a"


def validate_output(
    claim_id: str,
    out: LinkerOutput,
    turns: list[Turn],
    prep: PrepResult,
    indices: list[int],
    cfg: Settings,
) -> Validated:
    counts: Counter = Counter()
    counts["items_returned"] = len(out.items)
    allowed = set(indices)
    seen: set[str] = set()
    plain: list[_Plain] = []
    inference: list[LinkerItem] = []
    order: list[tuple[str, str]] = []  # (kind, key) in the LLM's order

    for item in out.items:
        if item.key in seen:
            counts["dup_key"] += 1
            continue
        seen.add(item.key)
        if item.link_type == "inference":
            inference.append(item)
            order.append(("inf", item.key))
            continue
        segs: dict[int, str] = {}
        for s in item.segments:
            if not s.text.strip():
                counts["empty_text"] += 1
            elif s.turn not in allowed or not 0 <= s.turn < len(turns):
                counts["not_in_shortlist"] += 1
            elif s.turn in segs:
                counts["dup_turn_segment"] += 1
            elif locate(turns[s.turn].text, s.text, None, cfg) is None:
                counts["unlocatable"] += 1
            else:
                segs[s.turn] = s.text
        if not segs:
            counts["item_dropped"] += 1
            continue
        ordered = _snap(sorted(segs.items()), turns, prep, counts)
        p = _Plain(item, ordered, item.role)
        p.status = answer_status([t for t, _ in ordered], prep)
        if p.status in ("question_only", "non_answer") and p.role == EvidenceRole.supporting:
            p.role = EvidenceRole.qualifying
            counts["coerced"] += 1
        plain.append(p)
        order.append(("plain", item.key))

    # dedup identical (turn set, role); later keys alias the kept one
    alias: dict[str, str] = {}
    kept: dict[tuple, _Plain] = {}
    deduped: list[_Plain] = []
    for p in plain:
        sig = (frozenset(t for t, _ in p.segs), p.role)
        if sig in kept:
            alias[p.item.key] = kept[sig].item.key
            counts["dedup"] += 1
        else:
            kept[sig] = p
            deduped.append(p)
    # cap, adverse items first
    if len(deduped) > cfg.link_max_items:
        keep = sorted(deduped, key=lambda p: _ADVERSE_FIRST[p.role])[: cfg.link_max_items]
        counts["capped"] = len(deduped) - len(keep)
        deduped = [p for p in deduped if p in keep]
    by_key = {p.item.key: p for p in deduped}

    def resolve(k: str) -> str:
        return alias.get(k, k)

    # inference: premises must be surviving non-inference items, plus a stated step
    valid_inf: dict[str, LinkerItem] = {}
    protected: set[str] = set()
    for inf in inference:
        prem = [resolve(k) for k in inf.premises]
        if prem and all(k in by_key for k in prem) and (inf.inference_step or "").strip():
            valid_inf[inf.key] = inf
            protected.update(prem)
        else:
            counts["inference_dropped"] += 1
            for k in prem:
                if k in by_key and k not in protected:
                    by_key[k].role = EvidenceRole.qualifying
    # (a premise demoted before a later valid inference protected it keeps the demotion: rare)

    final_keys = [
        (kind, k)
        for kind, k in order
        if (kind == "plain" and k in by_key) or (kind == "inf" and k in valid_inf)
    ]
    new_key = {k: f"{claim_id}:e{n}" for n, (_, k) in enumerate(final_keys, 1)}
    evidence: list[LinkedEvidence] = []
    cited: set[int] = set()
    for kind, k in final_keys:
        if kind == "plain":
            p = by_key[k]
            cited.update(t for t, _ in p.segs)
            draft = EvidenceDraft(
                key=new_key[k],
                role=p.role,
                segments=[ExcerptSegment(turn_index=t, text=x) for t, x in p.segs],
                note=p.item.note,
            )
            evidence.append(
                LinkedEvidence(draft=draft, link_type=p.item.link_type, answer_status=p.status)
            )
        else:
            inf = valid_inf[k]
            draft = EvidenceDraft(key=new_key[k], role=inf.role, segments=[], note=inf.note)
            evidence.append(
                LinkedEvidence(
                    draft=draft,
                    link_type="inference",
                    premise_keys=[new_key[resolve(x)] for x in inf.premises],
                    inference_step=(inf.inference_step or "").strip(),
                )
            )
    counts["items_kept"] = len(evidence)
    ambiguous = sorted(t for t in cited if prep.turns[t].role is None)
    return Validated(evidence=evidence, ambiguous_turns=ambiguous, counts=counts)
