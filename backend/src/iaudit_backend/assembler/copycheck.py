"""R5 (core): rule 9. Assessor text must be written, not copied from the transcript."""

import re
from dataclasses import dataclass

from iaudit_backend.models import AuditRequest, Verdict

from .normalize import normalize
from .repair import EXPLANATIONS, GENERIC_OUT_OF_SCOPE

_QUOTED = re.compile(r""""([^"]+)"|“([^”]+)”|‘([^’]+)’|(?<!\w)'(.+?)'(?!\w)""")
_WORDS = re.compile(r"[^\W_]+")
_TIME = re.compile(r"\b\d\d:\d\d\b")
_END = ".!?"
_MIN_QUOTE_WORDS = 4
COPY_WARNING = "Wording was adjusted to avoid reproducing transcript text."
_FALLBACK = {
    **EXPLANATIONS,
    Verdict.supported: "The cited excerpts support this claim.",
    Verdict.out_of_scope: "This statement is outside what the audit checks.",
}


@dataclass
class CopyContext:
    turns_norm: str  # all turns, normalized, joined by newline
    turn_texts: list[str]  # normalized, one per turn
    timestamps: list[str]
    ngram: int = 0  # word n-gram size; 0 disables the n-gram check
    turn_grams: frozenset[tuple[str, ...]] = frozenset()  # built once per request
    own_grams: frozenset[tuple[str, ...]] = frozenset()  # the assessor's own wording is allowed

    @classmethod
    def from_request(cls, req: AuditRequest, ngram: int = 8) -> "CopyContext":
        norms = [normalize(t.text)[0] for t in req.transcript]
        ts = [t.timestamp for t in req.transcript if t.timestamp]
        turn_grams: set[tuple[str, ...]] = set()
        own_grams: set[tuple[str, ...]] = set()
        if ngram > 0:
            for n in norms:
                turn_grams |= _grams(n, ngram)
            for s in req.assessment:
                own_grams |= _grams(normalize(s.text)[0], ngram)
        return cls("\n".join(norms), norms, ts, ngram, frozenset(turn_grams), frozenset(own_grams))


def _grams(normalized: str, n: int) -> set[tuple[str, ...]]:
    words = _WORDS.findall(normalized)
    return {tuple(words[i : i + n]) for i in range(len(words) - n + 1)}


def violates(text: str, ctx: CopyContext) -> bool:
    if _TIME.search(text) or any(ts in text for ts in ctx.timestamps):
        return True
    for m in _QUOTED.finditer(text):
        span = next(g for g in m.groups() if g is not None)
        if len(span.split()) >= _MIN_QUOTE_WORDS:
            n = normalize(span)[0].strip()
            if n and n in ctx.turns_norm:
                return True
    if ctx.ngram > 0:
        found = _grams(normalize(text)[0], ctx.ngram)
        if any(g in ctx.turn_grams and g not in ctx.own_grams for g in found):
            return True
    return False


def _sentences(text: str) -> list[str]:
    """Split on sentence ends that are not inside a quoted span."""
    masked = list(text)
    for m in _QUOTED.finditer(text):
        for i in range(m.start(), m.end()):
            if masked[i] in _END:
                masked[i] = "\x00"
    out, buf = [], []
    for i, ch in enumerate(masked):
        buf.append(text[i] if ch == "\x00" else ch)
        if ch in _END and (i + 1 == len(masked) or masked[i + 1].isspace()):
            out.append("".join(buf).strip())
            buf = []
    if "".join(buf).strip():
        out.append("".join(buf).strip())
    return [s for s in out if s]


def _clean(text: str, ctx: CopyContext) -> str | None:
    """Text without offending sentences; None when nothing is left. Unchanged if no violation."""
    if not violates(text, ctx):
        return text
    kept = [s for s in _sentences(text) if not violates(s, ctx)]
    rejoined = " ".join(kept)
    # a copied run can cross a sentence boundary: no single sentence violates, the whole does
    return rejoined if kept and not violates(rejoined, ctx) else None


def _is_turn_substring(note: str, ctx: CopyContext) -> bool:
    n = normalize(note)[0].strip()
    return bool(n) and any(n in t for t in ctx.turn_texts)


def scrub_claim(claim: dict, ctx: CopyContext, report) -> list[str]:
    """Repair rule 9 violations in place. Returns at most one warning note per claim."""
    changed = False
    verdict = Verdict(claim["verdict"])

    new = _clean(claim["explanation"], ctx)
    if new != claim["explanation"]:
        claim["explanation"] = new or _FALLBACK[verdict]
        report.repair("copy_explanation")
        changed = True

    for c in claim["concerns"]:
        new = _clean(c["explanation"], ctx)
        if new != c["explanation"]:
            c["explanation"] = new or (
                f"A possible {c['type'].replace('_', ' ')} concern was found; "
                "review the cited excerpts."
            )
            report.repair("copy_concern")
            changed = True

    for e in claim["evidence"]:
        note = e.get("note")
        if note is not None and (_is_turn_substring(note, ctx) or violates(note, ctx)):
            del e["note"]
            report.repair("copy_note")
            changed = True

    rev = claim.get("suggested_revision")
    if rev is not None and violates(rev, ctx):
        claim["suggested_revision"] = None
        report.repair("copy_revision")
        changed = True

    reason = claim.get("out_of_scope_reason")
    if reason is not None:
        new = _clean(reason, ctx)
        if new != reason:
            claim["out_of_scope_reason"] = new or GENERIC_OUT_OF_SCOPE
            report.repair("copy_reason")
            changed = True
    return [COPY_WARNING] if changed else []
