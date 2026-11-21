"""Reasons-audit mapping (SP03 R3): rating card -> eaudit request, eaudit response -> report.

Pure code, no model call. One eaudit `Section` per rated item that has a reason, example or note,
plus one `notes` section for the additional-notes box. Scores are display-only. Transcript turns
keep their order; eaudit `Pointer.index` is resolved with `sent_turn_ids` (turns) and
`section_ids` (claim spans). Evidence lines always carry the real transcript substring.
"""

from dataclasses import dataclass
from typing import Any

from eaudit.models import AuditRequest, AuditResponse, ConcernType, Pointer, Role, Section
from eaudit.models import Turn as EauditTurn
from eaudit.models.audit import Profile
from onolys_core.transcript import Transcript
from paudit.pack import Pack

from onolys_evaluation.report import AuditClaim, AuditEvidence, AuditItem, Line

NOTES_ID = "notes"
NOTES_LABEL = "Additional notes / evaluation reasoning"
SCHEMA_VERSION = "0.0.2"  # eaudit request contract version


@dataclass(frozen=True)
class ReasonsRequest:
    """The eaudit request plus the id lists needed to map the response back."""

    request: AuditRequest
    sent_turn_ids: list[str]
    section_ids: list[str]


def reasons_profile(pack: Pack) -> Profile | None:
    """`pack.yaml > evaluation.reasons_audit` as an eaudit profile; concern names are validated
    against the eaudit enum (an unknown name raises)."""
    cfg = ((pack.data.get("evaluation") or {}).get("reasons_audit")) or None
    if not cfg:
        return None
    return Profile(
        suppress_concerns=[ConcernType(c) for c in cfg.get("suppress_concerns") or []],
        context_note=cfg.get("context_note") or None,
    )


def _mmss(seconds: float) -> str:
    s = int(seconds)
    return f"{s // 60:02d}:{s % 60:02d}"


def _text(v: Any) -> str:
    return v.strip() if isinstance(v, str) else ""


def _section(item: dict[str, Any], entry: Any, text_field: str, value_field: str) -> Section | None:
    if not isinstance(entry, dict):
        return None
    parts = []
    if body := _text(entry.get(text_field)):
        parts.append(body)
    ex = entry.get("example")
    if isinstance(ex, dict) and (ex_text := _text(ex.get("text"))):
        at = ex.get("at_s")
        isnum = isinstance(at, int | float) and not isinstance(at, bool)
        parts.append(f"Example at {_mmss(at)}: {ex_text}" if isnum else f"Example: {ex_text}")
    if not parts:
        return None  # a value without any text has nothing to audit
    return Section(id=item["id"], label=item.get("label"), score=entry.get(value_field),
                   text="\n".join(parts))


def build_reasons_request(
    pack: Pack,
    transcript: Transcript,
    speaker_map: dict[str, Any],
    rating: dict[str, Any] | None,
    request_id: str | None = None,
) -> ReasonsRequest | None:
    """None when the card has no text to audit. Sections follow pack item order, then `notes`.
    Roles: `speaker_map["subject"]` (the clinician) -> interviewer, everyone else -> respondent."""
    if not isinstance(rating, dict):
        return None
    globals_, counts = rating.get("globals") or {}, rating.get("counts") or {}
    sections: list[Section] = []
    for item in pack.items:
        if item["kind"] == "global":
            sec = _section(item, globals_.get(item["id"]), "reason", "score")
        else:
            sec = _section(item, counts.get(item["id"]), "note", "count")
        if sec:
            sections.append(sec)
    if notes := _text(rating.get("notes")):
        sections.append(Section(id=NOTES_ID, label=NOTES_LABEL, text=notes))
    if not sections:
        return None
    subject = speaker_map.get("subject")
    turns = [
        EauditTurn.model_validate(
            d | {"role": Role.interviewer if t.speaker == subject else Role.respondent}
        )
        for t, d in zip(transcript.turns, transcript.to_eaudit_turns(), strict=True)
    ]
    request = AuditRequest(
        schema_version=SCHEMA_VERSION, request_id=request_id, transcript=turns,
        assessment=sections, profile=reasons_profile(pack),
    )
    return ReasonsRequest(request, [t.id for t in transcript.turns], [s.id for s in sections])


def _evidence_lines(role: str, start: Pointer, end: Pointer, texts: list[str],
                    ids: list[str]) -> list[AuditEvidence]:
    a, b = start.index, end.index
    if not (0 <= a <= b < len(ids)) or start.char < 0 or end.char < 0:
        return []
    out = []
    for i in range(a, b + 1):
        n = len(texts[i])
        lo = min(start.char, n) if i == a else 0
        hi = min(end.char, n) if i == b else n
        if hi > lo:
            out.append(AuditEvidence(turn_id=ids[i], start=lo, end=hi, quote=texts[i][lo:hi],
                                     role=role))
    return out


def map_reasons_response(response: AuditResponse, built: ReasonsRequest,
                         transcript: Transcript) -> list[AuditItem]:
    """One `AuditItem` per sent section (in order; claim-less sections have empty `claims`).
    Claims whose span points outside the sent sections are dropped; out-of-range evidence is
    dropped. `quote` is always the transcript substring, never model text."""
    texts = [t.text for t in transcript.turns]
    ids = built.sent_turn_ids
    sections = built.request.assessment
    items = [AuditItem(item_id=s.id, reason=s.text, claims=[]) for s in sections]
    for c in response.claims:
        si = c.span.start.index
        if not 0 <= si < len(sections):
            continue
        sec_text = sections[si].text
        lo = max(0, min(c.span.start.char, len(sec_text)))
        hi = len(sec_text)
        if c.span.end.index == si:
            hi = max(lo, min(c.span.end.char, hi))
        evidence = [ln for e in c.evidence
                    for ln in _evidence_lines(e.role.value, e.span.start, e.span.end, texts, ids)]
        items[si].claims.append(AuditClaim(
            span=sec_text[lo:hi], verdict=c.verdict.value, explanation=c.explanation,
            concerns=[k.type.value for k in c.concerns], evidence=evidence))
    return items


def support_lines(items: list[AuditItem], item_id: str) -> list[Line]:
    """Supporting evidence lines of `supported` claims for one item, as plain `Line`s for
    `compare.explain(support_lines=...)`."""
    return [Line(turn_id=e.turn_id, start=e.start, end=e.end, quote=e.quote)
            for it in items if it.item_id == item_id
            for c in it.claims if c.verdict == "supported"
            for e in c.evidence if e.role == "supporting"]
