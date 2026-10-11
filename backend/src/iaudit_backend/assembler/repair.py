"""R4: enforce contract rules 2-7 per claim after evidence drops. Never upgrades a verdict."""

from dataclasses import dataclass, field

from iaudit_backend.models import ConcernType, EvidenceRole, Verdict

from .claims import LocatedClaim
from .evidence import EvidenceResult
from .models import AssembleReport, Outcome

EXPLANATIONS = {
    Verdict.insufficient_evidence: (
        "The supplied interview does not establish this claim from the excerpts that could be "
        "verified."
    ),
    Verdict.partially_supported: (
        "Part of this claim is supported, but a contradicting excerpt also applies. "
        "Review the cited excerpts."
    ),
    Verdict.contradicted: "The cited excerpts conflict with this claim.",
}
STALLED_EXPLANATION = "This claim could not be audited in the available time."
GENERIC_OUT_OF_SCOPE = "This statement cannot be checked against the supplied interview."
UNSUPPORTED_CONCERN = "Nothing verifiable in the supplied interview establishes this claim."
CONTRADICTORY_CONCERN = "An excerpt in the supplied interview conflicts with this claim."
CHANGED_WARNING = "Verdict was adjusted because cited evidence could not be verified."
CONFLICT_WARNING = "Verdict was adjusted because a contradicting excerpt conflicts with it."
STALLED_WARNING = "Claim was not audited in the available time."


@dataclass
class RepairedClaim:
    """Claim fields without id/span, plus fixed-template warning messages for this claim."""

    claim: dict
    notes: list[str] = field(default_factory=list)


def _build_concerns(lc: LocatedClaim, ev: EvidenceResult, report: AssembleReport) -> list[dict]:
    out: list[dict] = []
    for c in lc.draft.concerns:
        ids: list[str] = []
        for k in c.evidence_keys:
            for i in ev.key_ids.get(k, []):
                if i not in ids:
                    ids.append(i)
        if c.evidence_keys and not ids:
            report.repair("concern_removed")
            continue
        _merge_concern(out, c.type.value, c.explanation, ids)
    return out


def _merge_concern(concerns: list[dict], type_: str, explanation: str, ids: list[str]) -> None:
    for c in concerns:
        if c["type"] == type_:
            c["evidence_ids"] = c["evidence_ids"] + [i for i in ids if i not in c["evidence_ids"]]
            return
    concerns.append({"type": type_, "explanation": explanation, "evidence_ids": list(ids)})


def repair_claim(lc: LocatedClaim, ev: EvidenceResult, report: AssembleReport) -> RepairedClaim:
    d = lc.draft
    if d.outcome == Outcome.stalled:
        report.repair("stalled")
        return RepairedClaim(
            {
                "verdict": Verdict.insufficient_evidence.value,
                "explanation": STALLED_EXPLANATION,
                "suggested_revision": None,
                "concerns": [],
                "evidence": [],
            },
            [STALLED_WARNING],
        )

    verdict = d.verdict
    if verdict == Verdict.out_of_scope:
        claim = {
            "verdict": verdict.value,
            "explanation": d.explanation,
            "out_of_scope_reason": d.out_of_scope_reason or GENERIC_OUT_OF_SCOPE,
            "suggested_revision": d.suggested_revision,
            "concerns": [],
            "evidence": [],
        }
        if not d.out_of_scope_reason:
            report.repair("out_of_scope_reason_filled")
        if d.concerns or ev.items:
            report.repair("out_of_scope_stripped")
        return RepairedClaim(claim)

    evidence = [dict(i) for i in ev.items]
    concerns = _build_concerns(lc, ev, report)
    explanation, revision = d.explanation, d.suggested_revision

    def ids_of(role: EvidenceRole) -> list[str]:
        return [e["id"] for e in evidence if e["role"] == role.value]

    changed = False
    conflict = False

    def change(new: Verdict, code: str) -> None:
        nonlocal verdict, changed, conflict
        verdict, changed = new, True
        conflict = conflict or code.endswith("_with_contradiction")
        report.repair(code)

    if verdict == Verdict.supported and not ids_of(EvidenceRole.supporting):
        change(Verdict.insufficient_evidence, "supported_no_support")
        _merge_concern(concerns, ConcernType.unsupported_claim.value, UNSUPPORTED_CONCERN, [])
    if verdict == Verdict.supported and ids_of(EvidenceRole.contradicting):
        change(Verdict.partially_supported, "supported_with_contradiction")
        _merge_concern(
            concerns,
            ConcernType.contradictory_evidence.value,
            CONTRADICTORY_CONCERN,
            ids_of(EvidenceRole.contradicting),
        )
    if verdict == Verdict.contradicted and not ids_of(EvidenceRole.contradicting):
        change(Verdict.insufficient_evidence, "contradicted_no_contradiction")
    if verdict == Verdict.partially_supported and not concerns:
        change(Verdict.insufficient_evidence, "partial_no_concerns")
    if verdict == Verdict.insufficient_evidence and ids_of(EvidenceRole.contradicting):
        change(Verdict.contradicted, "insufficient_with_contradiction")

    notes: list[str] = []
    if changed:
        explanation, revision = EXPLANATIONS[verdict], None
        notes.append(CONFLICT_WARNING if conflict else CHANGED_WARNING)
    return RepairedClaim(
        {
            "verdict": verdict.value,
            "explanation": explanation,
            "suggested_revision": revision,
            "concerns": concerns,
            "evidence": evidence,
        },
        notes,
    )
