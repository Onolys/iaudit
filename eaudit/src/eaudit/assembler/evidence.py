"""R2: evidence resolution. Search only the cited turn; merge or split cross-turn segments."""

from dataclasses import dataclass, field

from eaudit.config import Settings
from eaudit.models import Turn

from .locate import locate
from .models import AssembleReport, EvidenceDraft


@dataclass
class EvidenceResult:
    items: list[dict] = field(default_factory=list)
    key_ids: dict[str, list[str]] = field(default_factory=dict)


@dataclass
class _Hit:
    turn: int
    start: int
    end: int


def _at_tail(text: str, end: int, slack: int) -> bool:
    tail = text[end:]
    return not tail.strip() or len(tail) <= slack


def _at_head(text: str, start: int, slack: int) -> bool:
    return not text[:start].strip() or start <= slack


def _group(hits: list[_Hit], turns: list[Turn], slack: int) -> list[list[_Hit]]:
    """Chain consecutive-turn hits only when the walk adds no extra text."""
    groups: list[list[_Hit]] = []
    for h in hits:
        if groups:
            prev = groups[-1][-1]
            if (
                h.turn == prev.turn + 1
                and _at_tail(turns[prev.turn].text, prev.end, slack)
                and _at_head(turns[h.turn].text, h.start, slack)
            ):
                groups[-1].append(h)
                continue
        groups.append([h])
    return groups


def resolve_evidence(
    drafts: list[EvidenceDraft], turns: list[Turn], cfg: Settings, report: AssembleReport
) -> EvidenceResult:
    res = EvidenceResult()
    seen: dict[tuple, str] = {}
    for d in drafts:
        hits: list[_Hit] = []
        for seg in d.segments:
            if not 0 <= seg.turn_index < len(turns):
                report.drop("segment_bad_turn")
                continue
            m = locate(turns[seg.turn_index].text, seg.text, seg.char_hint, cfg)
            if m is None:
                report.drop("segment_unmatched")
                continue
            report.evidence_tiers[m.tier] += 1
            report.evidence_scores.append(m.score)
            report.occurrences.append(m.occurrences)
            hits.append(_Hit(seg.turn_index, m.start, m.end))
        if not hits:
            report.drop("evidence_unmatched")
            continue
        ids: list[str] = []
        for n, grp in enumerate(_group(hits, turns, cfg.cross_turn_slack)):
            first, last = grp[0], grp[-1]
            sig = (d.role, first.turn, first.start, last.turn, last.end)
            if sig not in seen:
                eid = f"e{len(res.items) + 1}"
                seen[sig] = eid
                item = {
                    "id": eid,
                    "role": d.role.value,
                    "span": {
                        "start": {"index": first.turn, "char": first.start},
                        "end": {"index": last.turn, "char": last.end},
                    },
                }
                if n == 0 and d.note:
                    item["note"] = d.note
                res.items.append(item)
            if seen[sig] not in ids:
                ids.append(seen[sig])
        res.key_ids[d.key] = ids
    return res
