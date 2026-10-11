"""Acceptance 1: drafts equivalent to docs/contracts/examples reproduce every span."""

import copy

from iaudit_backend.assembler import (
    ClaimDraft,
    ConcernDraft,
    EvidenceDraft,
    ExcerptSegment,
    InternalAudit,
    assemble,
)
from iaudit_backend.config import Settings
from iaudit_backend.contract import validate_response
from iaudit_backend.models import AuditRequest


def seg(turn, text):
    return ExcerptSegment(turn_index=turn, text=text)


def drafts() -> InternalAudit:
    return InternalAudit(
        claims=[
            ClaimDraft(
                key="supported",
                section_index=0,
                segments=["The caregiver reported two medication lapses last month."],
                verdict="supported",
                explanation="",
                evidence=[
                    EvidenceDraft(
                        key="cg",
                        role="supporting",
                        segments=[seg(4, "She forgot her medication twice last month.")],
                    ),
                    EvidenceDraft(
                        key="ill",
                        role="qualifying",
                        segments=[seg(5, "That was only while I had the flu. I'm fine now.")],
                        note="",
                    ),
                ],
            ),
            ClaimDraft(
                key="contradicted",
                section_index=0,
                segments=["The patient frequently loses their keys."],
                verdict="contradicted",
                explanation="",
                evidence=[
                    EvidenceDraft(
                        key="den",
                        role="contradicting",
                        segments=[seg(1, "No. I don't lose my keys.")],
                        note="",
                    )
                ],
                concerns=[
                    ConcernDraft(type="negation_reversal", explanation="", evidence_keys=["den"]),
                    ConcernDraft(
                        type="frequency_severity_inflation", explanation="", evidence_keys=["den"]
                    ),
                ],
            ),
            ClaimDraft(
                key="partial",
                section_index=0,
                segments=["They missed appointments throughout the past year."],
                verdict="partially_supported",
                explanation="",
                evidence=[
                    EvidenceDraft(
                        key="appt",
                        role="qualifying",
                        segments=[
                            seg(2, "What about appointments?"),
                            seg(3, "I missed one last year, when I was traveling."),
                        ],
                        note="",
                    )
                ],
                concerns=[
                    ConcernDraft(
                        type="frequency_severity_inflation", explanation="", evidence_keys=["appt"]
                    ),
                    ConcernDraft(type="context_stripping", explanation="", evidence_keys=["appt"]),
                ],
            ),
            ClaimDraft(
                key="insufficient",
                section_index=0,
                segments=["The patient has trouble at work."],
                verdict="insufficient_evidence",
                explanation="",
                concerns=[ConcernDraft(type="unsupported_claim", explanation="")],
            ),
            ClaimDraft(
                key="oos",
                section_index=0,
                segments=["This meets criterion A for a memory disorder."],
                verdict="out_of_scope",
                explanation="",
                out_of_scope_reason="",
            ),
        ]
    )


def fill_text(internal: InternalAudit, expected: dict) -> InternalAudit:
    """Copy the example's written fields (not spans) into the drafts."""
    by_key = dict(zip((c.key for c in internal.claims), expected["claims"], strict=True))
    for c in internal.claims:
        e = by_key[c.key]
        c.explanation = e["explanation"]
        c.suggested_revision = e.get("suggested_revision")
        c.out_of_scope_reason = e.get("out_of_scope_reason") or None
        for cd, ec in zip(c.concerns, e["concerns"], strict=True):
            cd.explanation = ec["explanation"]
        for ed, ee in zip(c.evidence, e["evidence"], strict=True):
            if ed.note is not None:
                ed.note = ee["note"]
    return internal


def canonical(resp: dict) -> dict:
    """Rename ids by position so only structure and spans are compared."""
    out = copy.deepcopy(resp)
    for n, c in enumerate(out["claims"], 1):
        ids = {e["id"]: f"e{i}" for i, e in enumerate(c["evidence"], 1)}
        c["id"] = f"c{n}"
        for e in c["evidence"]:
            e["id"] = ids[e["id"]]
        for k in c["concerns"]:
            k["evidence_ids"] = [ids[i] for i in k["evidence_ids"]]
    return out


def test_reproduces_example_response(example_request, example_response):
    internal = fill_text(drafts(), example_response)
    out = assemble(AuditRequest.model_validate(example_request), internal, Settings())
    assert validate_response(out.response) == []
    assert canonical(out.response) == canonical(example_response)


def test_named_spans_from_acceptance(example_request, example_response):
    internal = fill_text(drafts(), example_response)
    resp = assemble(AuditRequest.model_validate(example_request), internal, Settings()).response
    contradicted = resp["claims"][1]["span"]
    assert (contradicted["start"]["char"], contradicted["end"]["char"]) == (57, 97)
    appt = resp["claims"][2]["evidence"][0]["span"]
    assert appt == {"start": {"index": 2, "char": 0}, "end": {"index": 3, "char": 45}}


def test_report_counts_for_example(example_request, example_response):
    internal = fill_text(drafts(), example_response)
    out = assemble(AuditRequest.model_validate(example_request), internal, Settings())
    assert out.report.evidence_tiers["exact"] == 5  # 4 evidence items, one with 2 segments
    assert not out.report.drops and not out.report.repairs


def test_logs_report_and_warnings_hold_no_transcript_text(
    example_request, example_response, caplog, monkeypatch
):
    import logging

    import iaudit_backend.assembler as pkg
    from iaudit_backend.assembler.repair import RepairedClaim

    canary = "zebracanary quokka"
    example_request["transcript"][1]["text"] = f"No. {canary} keys."
    example_request["assessment"][0]["text"] = (
        f"{canary} claim sentence. " + example_request["assessment"][0]["text"]
    )
    # force a quarantine so the validation logger fires
    monkeypatch.setattr(
        pkg,
        "repair_claim",
        lambda lc, ev, r: RepairedClaim(
            {
                "verdict": "supported",
                "explanation": "x",
                "suggested_revision": None,
                "concerns": [],
                "evidence": [],
            }
        ),
    )
    internal = InternalAudit(
        claims=[
            ClaimDraft(
                key="a",
                section_index=0,
                segments=[f"{canary} claim sentence."],
                verdict="supported",
                explanation="x",
            )
        ]
    )
    with caplog.at_level(logging.DEBUG, logger="iaudit"):
        out = assemble(AuditRequest.model_validate(example_request), internal, Settings())
    blob = caplog.text + out.report.model_dump_json() + repr(out.response["warnings"])
    assert caplog.records and "zebracanary" not in blob
