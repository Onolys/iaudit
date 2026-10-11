from iaudit_backend.assembler import (
    AssembleReport,
    ClaimDraft,
    ConcernDraft,
    EvidenceDraft,
    ExcerptSegment,
    InternalAudit,
    SectionFailure,
    assemble,
)
from iaudit_backend.config import Settings
from iaudit_backend.models import AuditRequest


def _draft() -> InternalAudit:
    return InternalAudit(
        claims=[
            ClaimDraft(
                key="k1",
                section_index=0,
                segments=["a claim"],
                span_hint=(0, 7),
                verdict="supported",
                explanation="why",
                concerns=[
                    ConcernDraft(type="unsupported_claim", explanation="x", evidence_keys=["e"])
                ],
                evidence=[
                    EvidenceDraft(
                        key="e",
                        role="supporting",
                        segments=[ExcerptSegment(turn_index=1, text="hello", char_hint=3)],
                    )
                ],
                ambiguous_turns=[2],
            )
        ],
        section_failures=[SectionFailure(section_index=1, reason="timeout")],
        truncated=True,
    )


def test_internal_audit_round_trips():
    d = _draft()
    assert InternalAudit.model_validate(d.model_dump()) == d
    assert InternalAudit.model_validate_json(d.model_dump_json()) == d


def test_report_has_only_counts():
    for name, field in AssembleReport.model_fields.items():
        assert "text" not in name
        assert "str" not in str(field.annotation).replace("Counter[str", "")


def test_assemble_echoes_request_id(example_request):
    req = AuditRequest.model_validate(example_request)
    out = assemble(req, InternalAudit(), Settings())
    assert out.response["request_id"] == "example-001"
    assert out.response["status"] == "partial"  # section 0 has text but no claims
    assert isinstance(out.report, AssembleReport)


def test_assemble_omits_missing_request_id(example_request):
    example_request.pop("request_id")
    req = AuditRequest.model_validate(example_request)
    assert "request_id" not in assemble(req, InternalAudit(), Settings()).response
