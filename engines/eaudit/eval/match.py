"""R7: match response claims to gold claims by span overlap (code points, per section)."""

from dataclasses import dataclass, field

from eaudit.models import Verdict
from eval.gold import GoldClaim

OVERLAP_MIN = 0.5
# Same order as the assembler's overlap policy: worst first.
SEVERITY = {
    Verdict.contradicted.value: 4,
    Verdict.partially_supported.value: 3,
    Verdict.insufficient_evidence.value: 2,
    Verdict.supported.value: 1,
    Verdict.out_of_scope.value: 0,
}


def span_of(claim: dict) -> tuple[int, int, int] | None:
    """(section, start, end) or None for a claim that crosses sections."""
    s, e = claim["span"]["start"], claim["span"]["end"]
    if s["index"] != e["index"]:
        return None
    return s["index"], s["char"], e["char"]


def _inter(a: tuple[int, int], b: tuple[int, int]) -> int:
    return max(0, min(a[1], b[1]) - max(a[0], b[0]))


@dataclass
class Matched:
    gold: GoldClaim
    preds: list[dict]  # response claims; several when the atomizer split the gold claim

    @property
    def verdict(self) -> str:
        return max((p["verdict"] for p in self.preds), key=lambda v: SEVERITY[v])

    @property
    def concerns(self) -> set[str]:
        return {c["type"] for p in self.preds for c in p["concerns"]}

    @property
    def explanation(self) -> str:
        return " ".join(p["explanation"] for p in self.preds).lower()

    @property
    def evidence(self) -> list[dict]:
        return [e for p in self.preds for e in p["evidence"]]


@dataclass
class MatchResult:
    matched: list[Matched] = field(default_factory=list)
    extras: list[dict] = field(default_factory=list)  # response claims matching no gold claim
    missed: list[GoldClaim] = field(default_factory=list)


def match_claims(gold: list[GoldClaim], claims: list[dict]) -> MatchResult:
    spans = {id(c): span_of(c) for c in claims}
    pairs = []  # (-iou, gold start, pred start, gold index, pred index)
    for gi, g in enumerate(gold):
        for pi, c in enumerate(claims):
            sp = spans[id(c)]
            if sp is None or sp[0] != g.section_index:
                continue
            inter = _inter((g.start, g.end), (sp[1], sp[2]))
            smallest = min(g.end - g.start, sp[2] - sp[1])
            if smallest <= 0 or inter / smallest < OVERLAP_MIN:
                continue
            union = (g.end - g.start) + (sp[2] - sp[1]) - inter
            pairs.append((-inter / union, g.start, sp[1], gi, pi))
    pairs.sort()
    taken_g: dict[int, list[int]] = {}
    taken_p: set[int] = set()
    for _, _, _, gi, pi in pairs:
        if gi not in taken_g and pi not in taken_p:
            taken_g[gi] = [pi]
            taken_p.add(pi)
    # a finer atomizer: leftover predicted claims lying wholly inside a matched gold span
    for pi, c in enumerate(claims):
        sp = spans[id(c)]
        if pi in taken_p or sp is None:
            continue
        for gi in taken_g:
            g = gold[gi]
            if sp[0] == g.section_index and g.start <= sp[1] and sp[2] <= g.end:
                taken_g[gi].append(pi)
                taken_p.add(pi)
                break
    out = MatchResult()
    for gi, g in enumerate(gold):
        if gi in taken_g:
            out.matched.append(Matched(g, [claims[i] for i in taken_g[gi]]))
        else:
            out.missed.append(g)
    out.extras = [c for pi, c in enumerate(claims) if pi not in taken_p]
    return out
