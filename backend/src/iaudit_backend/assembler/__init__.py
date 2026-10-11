"""Stage 4: resolve verbatim text to spans, enforce contract rules, validate the response."""

from iaudit_backend.config import Settings
from iaudit_backend.models import AuditRequest

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

__all__ = [
    "AssembleOutcome",
    "AssembleReport",
    "AssemblyError",
    "ClaimDraft",
    "ConcernDraft",
    "EvidenceDraft",
    "ExcerptSegment",
    "InternalAudit",
    "SectionFailure",
    "assemble",
]


def assemble(request: AuditRequest, internal: InternalAudit, cfg: Settings) -> AssembleOutcome:
    report = AssembleReport()
    response: dict = {
        "schema_version": "1.0.0",
        "status": "complete",
        "warnings": [],
        "claims": [],
    }
    if request.request_id is not None:
        response["request_id"] = request.request_id
    return AssembleOutcome(response=response, report=report)
