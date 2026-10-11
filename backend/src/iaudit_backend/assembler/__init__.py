"""Stage 4: resolve verbatim text to spans, enforce contract rules, validate the response."""

from iaudit_backend.config import Settings
from iaudit_backend.models import AuditRequest

from . import warnings as w
from .bounds import span_in_bounds
from .claims import resolve_claims
from .copycheck import CopyContext, scrub_claim
from .evidence import resolve_evidence
from .locate import Match, locate
from .models import (
    AssembleOutcome,
    AssembleReport,
    AssemblyError,
    ClaimDraft,
    ConcernDraft,
    EvidenceDraft,
    ExcerptSegment,
    InternalAudit,
    SectionFailure,
)
from .repair import repair_claim

__all__ = [
    "AssembleOutcome",
    "AssembleReport",
    "AssemblyError",
    "ClaimDraft",
    "ConcernDraft",
    "EvidenceDraft",
    "ExcerptSegment",
    "InternalAudit",
    "Match",
    "SectionFailure",
    "assemble",
    "locate",
]


def assemble(request: AuditRequest, internal: InternalAudit, cfg: Settings) -> AssembleOutcome:
    report = AssembleReport()
    turn_lens = [len(t.text) for t in request.transcript]
    sec_lens = [len(s.text) for s in request.assessment]
    copy_ctx = CopyContext.from_request(request)

    res = resolve_claims(
        internal.claims, request.assessment, internal.section_failures, cfg, report
    )
    section_warnings = [
        w.section_warning(f.section_index, f.reason) for f in internal.section_failures
    ] + [w.section_warning(i, reason) for i, reason in res.unprocessed]

    claims: list[dict] = []
    claim_warnings: list[dict] = []
    for lc in res.claims:
        span = {
            "start": {"index": lc.section, "char": lc.start},
            "end": {"index": lc.section, "char": lc.end},
        }
        if not span_in_bounds(span, sec_lens, single_index=True):
            report.drop("claim_out_of_range")
            claim_warnings.append(w.claim_warning("span_out_of_range", w.OUT_OF_RANGE, lc.id))
            continue
        ev = resolve_evidence(lc.draft.evidence, request.transcript, cfg, report)
        bad = {i["id"] for i in ev.items if not span_in_bounds(i["span"], turn_lens)}
        if bad:
            report.drop("evidence_out_of_range")
            ev.items = [i for i in ev.items if i["id"] not in bad]
            ev.key_ids = {
                k: [i for i in ids if i not in bad]
                for k, ids in ev.key_ids.items()
                if any(i not in bad for i in ids)
            }
            claim_warnings.append(w.claim_warning("span_out_of_range", w.OUT_OF_RANGE, lc.id))
        rep = repair_claim(lc, ev, report)
        notes = rep.notes + scrub_claim(rep.claim, copy_ctx, report)
        if lc.draft.ambiguous_turns:
            claim_warnings.append(w.ambiguous_warning(lc.draft.ambiguous_turns, lc.id))
        claim_warnings += [w.claim_warning("other", n, lc.id) for n in notes]
        claims.append({"id": lc.id, "span": span, **rep.claim})

    id_of = {lc.key: lc.id for lc in res.claims}
    aggregates = [w.truncated_warning()] if internal.truncated else []
    aggregates += [w.event_warning(e, id_of) for e in res.events]
    warnings = section_warnings + claim_warnings + aggregates

    response: dict = {
        "schema_version": "1.0.0",
        "status": (
            "partial" if any(x["code"] == "section_not_processed" for x in warnings) else "complete"
        ),
        "warnings": warnings,
        "claims": claims,
    }
    if request.request_id is not None:
        response["request_id"] = request.request_id
    return AssembleOutcome(response=response, report=report)
