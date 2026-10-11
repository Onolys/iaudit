"""R9: resolve segments with 02's locate(), check the output, compute span hints.

03 has no matcher of its own: every offset comes from `assembler.locate`.
"""

import re
from dataclasses import dataclass, field

from iaudit_backend.assembler.locate import locate
from iaudit_backend.config import Settings

from .models import AtomizerOutput, CausalLink, RawClaim
from .prompt import Speaker

_SENT = re.compile(r"[^.!?]+[.!?]*")
_WORD = re.compile(r"\w+")
MIN_SENTENCE_WORDS = 5
TRIVIAL_WORDS = 3  # shorter section text is not worth a "no claims" failure


@dataclass
class Resolved:
    ref: str
    raw: RawClaim
    segments: list[str]  # exact substrings of the section text
    regions: list[tuple[int, int]]
    hint: tuple[int, int]
    quality: str = "covering"


@dataclass
class Checked:
    valid: list[Resolved] = field(default_factory=list)  # document order
    links: list[CausalLink] = field(default_factory=list)  # still in refs
    errors: list[tuple[str, str]] = field(default_factory=list)  # (claim ref | "section", kind)
    dropped: int = 0
    gaps: int = 0


def is_trivial(text: str) -> bool:
    return len(_WORD.findall(text)) < TRIVIAL_WORDS


def _overlaps(a: tuple[int, int], b: tuple[int, int]) -> bool:
    return a[0] < b[1] and b[0] < a[1]


def _resolve_segments(
    text: str, segments: list[str], assigned: list[tuple[int, int]], cfg: Settings
) -> tuple[list[tuple[int, int]] | None, str | None]:
    """Locate each segment in document order, skipping hits that overlap earlier claims."""
    ccfg = cfg.model_copy(update={"fuzzy_threshold": cfg.claim_fuzzy_threshold})
    regions: list[tuple[int, int]] = []
    pos = 0
    saw_overlap = False
    for seg in segments:
        found = None
        scan = pos
        while scan <= len(text):
            m = locate(text[scan:], seg, None, ccfg)
            if m is None:
                break
            region = (m.start + scan, m.end + scan)
            if any(_overlaps(region, a) for a in assigned):
                saw_overlap = True
                scan = region[0] + 1
                continue
            found = region
            break
        if found is None:
            return None, "overlap" if saw_overlap else "unresolved_segment"
        regions.append(found)
        pos = found[1]
    return regions, None


def _sentences(text: str) -> list[tuple[int, int]]:
    return [(m.start(), m.end()) for m in _SENT.finditer(text) if m.group().strip()]


def check_output(out: AtomizerOutput, text: str, roster: list[Speaker], cfg: Settings) -> Checked:
    res = Checked()
    known = {s.speaker for s in roster}
    seen_refs: set[str] = set()
    assigned: list[tuple[int, int]] = []
    for c in out.claims:
        if c.ref in seen_refs:
            res.errors.append((c.ref, "duplicate_id"))
            res.dropped += 1
            continue
        seen_refs.add(c.ref)
        if (c.scope == "out_of_scope") != (c.oos_category is not None):
            res.errors.append((c.ref, "bad_category"))  # checked per claim, not at parse time
            res.dropped += 1
            continue
        if len(res.valid) >= cfg.atomize_max_claims:
            res.dropped += 1  # over the cap: counted, not retried
            continue
        regions, err = _resolve_segments(text, c.segments, assigned, cfg)
        if regions is None:
            res.errors.append((c.ref, err))
            res.dropped += 1
            continue
        assigned.extend(regions)
        fixed = c.model_copy(
            update={
                "subject_speaker": c.subject_speaker if c.subject_speaker in known else None,
                "reported_by": [
                    r.model_copy(update={"speaker": r.speaker if r.speaker in known else None})
                    for r in c.reported_by
                ],
            }
        )
        res.valid.append(
            Resolved(
                c.ref,
                fixed,
                [text[s:e] for s, e in regions],
                regions,
                (regions[0][0], regions[-1][1]),
            )
        )
    # span quality: a covering range that swallows another claim's segment is anchor-only
    for r in res.valid:
        others = [reg for o in res.valid if o is not r for reg in o.regions]
        if any(_overlaps(r.hint, o) for o in others):
            r.quality = "anchor_only"
            r.hint = max(r.regions, key=lambda reg: reg[1] - reg[0])
    res.valid.sort(key=lambda r: r.regions[0][0])
    # links must point at kept claims
    refs = {r.ref for r in res.valid}
    for link in out.links:
        if link.effect_id in refs and all(i in refs for i in link.cause_ids):
            res.links.append(link)
        else:
            res.errors.append(("section", "bad_link"))
    # coverage: every sentence of 5+ words needs a claim
    covered = [reg for r in res.valid for reg in r.regions]
    for s, e in _sentences(text):
        if len(_WORD.findall(text[s:e])) >= MIN_SENTENCE_WORDS and not any(
            _overlaps((s, e), c) for c in covered
        ):
            res.gaps += 1
    if res.gaps:
        res.errors.append(("section", "coverage_gap"))
    if not out.claims and not is_trivial(text):
        res.errors.append(("section", "empty_output"))
    return res
