"""R3: claim span resolution and the rule 8 overlap policy."""

from dataclasses import dataclass, field

from iaudit_backend.config import Settings
from iaudit_backend.models import Section, Verdict

from .locate import locate
from .models import AssembleReport, ClaimDraft, SectionFailure
from .normalize import normalize

_SEVERITY = {
    Verdict.contradicted: 4,
    Verdict.partially_supported: 3,
    Verdict.insufficient_evidence: 2,
    Verdict.supported: 1,
    Verdict.out_of_scope: 0,
}


@dataclass
class LocatedClaim:
    draft: ClaimDraft
    section: int
    start: int
    end: int
    id: str = ""

    @property
    def key(self) -> str:
        return self.draft.key

    @property
    def severity(self) -> int:
        return _SEVERITY[self.draft.verdict]


@dataclass
class ClaimEvent:
    """A drop or unlocatable claim. Holds keys and indexes only, never text."""

    kind: str  # unlocatable | overlap_nested | overlap_identical | overlap_partial
    key: str
    section_index: int
    kept_key: str | None = None


@dataclass
class ClaimResult:
    claims: list[LocatedClaim] = field(default_factory=list)
    events: list[ClaimEvent] = field(default_factory=list)
    unprocessed: list[tuple[int, str]] = field(default_factory=list)


def _trim(text: str, start: int, end: int) -> tuple[int, int] | None:
    while start < end and text[start].isspace():
        start += 1
    while end > start and text[end - 1].isspace():
        end -= 1
    return (start, end) if end > start else None


def _hint_valid(text: str, hint: tuple[int, int], segments: list[str]) -> bool:
    s, e = hint
    if not 0 <= s < e <= len(text):
        return False
    window, _ = normalize(text[s:e])
    pos = 0
    for seg in segments:
        nseg = normalize(seg)[0].strip()
        if not nseg:
            return False
        i = window.find(nseg, pos)
        if i == -1:
            return False
        pos = i + len(nseg)
    return True


def _resolve(d: ClaimDraft, text: str, cfg: Settings) -> tuple[int, int, str] | None:
    if d.span_hint is not None and _hint_valid(text, d.span_hint, d.segments):
        t = _trim(text, *d.span_hint)
        if t:
            return t[0], t[1], "hint"
    ccfg = cfg.model_copy(update={"fuzzy_threshold": cfg.claim_fuzzy_threshold})
    hint = d.span_hint[0] if d.span_hint else None
    pos, first, last, worst = 0, None, 0, "exact"
    rank = {"exact": 0, "normalized": 1, "fuzzy": 2}
    for seg in d.segments:
        m = locate(text[pos:], seg, None if hint is None else hint - pos, ccfg)
        if m is None:
            return None
        if first is None:
            first = m.start + pos
        last = m.end + pos
        pos = last
        if rank[m.tier] > rank[worst]:
            worst = m.tier
    if first is None:
        return None
    return first, last, worst


_MIN_TRIMMED_CHARS = 3


def _try_trim(loser: LocatedClaim, other: LocatedClaim, text: str) -> bool:
    """Cut the loser's overlapping end. False (loser untouched) if too little text would remain."""
    start, end = loser.start, loser.end
    if loser.start < other.start:  # loser comes first: cut its tail
        end = other.start
        while end > start and text[end - 1].isspace():
            end -= 1
    else:  # loser comes second: cut its head
        start = other.end
        while start < end and text[start].isspace():
            start += 1
    if sum(not ch.isspace() for ch in text[start:end]) < _MIN_TRIMMED_CHARS:
        return False
    loser.start, loser.end = start, end
    return True


def _drop_overlaps(
    located: list[LocatedClaim],
    events: list[ClaimEvent],
    report: AssembleReport,
    text: str = "",
    trim: bool = False,
) -> list[LocatedClaim]:
    def drop(c: LocatedClaim, kind: str, kept: LocatedClaim) -> None:
        events.append(ClaimEvent(kind, c.key, c.section, kept.key))
        report.drop(kind)

    # Identical spans: keep the more severe, tie first.
    kept: list[LocatedClaim] = []
    for c in located:
        twin = next((k for k in kept if (k.start, k.end) == (c.start, c.end)), None)
        if twin is None:
            kept.append(c)
        elif c.severity > twin.severity:
            kept[kept.index(twin)] = c
            drop(twin, "overlap_identical", c)
        else:
            drop(c, "overlap_identical", twin)
    # Nested: drop the outer, keep the narrower claims.
    out = []
    for c in kept:
        inner = next(
            (o for o in kept if o is not c and c.start <= o.start and o.end <= c.end), None
        )
        if inner is not None:
            drop(c, "overlap_nested", inner)
        else:
            out.append(c)
    # Partial overlap: drop the less severe (tie: the later one).
    out.sort(key=lambda c: (c.start, c.end))
    i = 0
    while i < len(out) - 1:
        a, b = out[i], out[i + 1]
        if b.start < a.end:
            loser, winner = (a, b) if b.severity > a.severity else (b, a)
            if trim and _try_trim(loser, winner, text):
                events.append(ClaimEvent("overlap_trimmed", loser.key, loser.section, winner.key))
                report.repair("overlap_trimmed")
                out.sort(key=lambda c: (c.start, c.end))
                i = 0
                continue
            drop(loser, "overlap_partial", winner)
            out.remove(loser)
            i = max(i - 1, 0)
        else:
            i += 1
    return out


def resolve_claims(
    drafts: list[ClaimDraft],
    sections: list[Section],
    failures: list[SectionFailure],
    cfg: Settings,
    report: AssembleReport,
) -> ClaimResult:
    res = ClaimResult()
    by_section: dict[int, list[LocatedClaim]] = {}
    for d in drafts:
        if not 0 <= d.section_index < len(sections):
            report.drop("claim_unlocatable")
            res.events.append(ClaimEvent("unlocatable", d.key, d.section_index))
            continue
        r = _resolve(d, sections[d.section_index].text, cfg)
        if r is None:
            report.drop("claim_unlocatable")
            res.events.append(ClaimEvent("unlocatable", d.key, d.section_index))
            continue
        report.claim_tiers[r[2]] += 1
        by_section.setdefault(d.section_index, []).append(
            LocatedClaim(d, d.section_index, r[0], r[1])
        )
    failed = {f.section_index for f in failures}
    for idx, section in enumerate(sections):
        located = by_section.get(idx, [])
        if located:
            res.claims.extend(
                _drop_overlaps(located, res.events, report, section.text, cfg.overlap_trim)
            )
        elif section.text.strip() and idx not in failed:
            res.unprocessed.append((idx, "no_claims_located"))
    res.claims.sort(key=lambda c: (c.section, c.start))
    for n, c in enumerate(res.claims, 1):
        c.id = f"c{n}"
    return res
