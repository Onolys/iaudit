from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict


class Role(StrEnum):
    interviewer = "interviewer"
    respondent = "respondent"
    informant = "informant"
    other = "other"


class Verdict(StrEnum):
    supported = "supported"
    partially_supported = "partially_supported"
    contradicted = "contradicted"
    insufficient_evidence = "insufficient_evidence"
    out_of_scope = "out_of_scope"


class ConcernType(StrEnum):
    """Mission checks 1-12, in order."""

    unsupported_claim = "unsupported_claim"
    contradictory_evidence = "contradictory_evidence"
    wrong_attribution = "wrong_attribution"
    timeframe_mismatch = "timeframe_mismatch"
    negation_reversal = "negation_reversal"
    certainty_inflation = "certainty_inflation"
    frequency_severity_inflation = "frequency_severity_inflation"
    context_stripping = "context_stripping"
    question_as_answer = "question_as_answer"
    correction_ignored = "correction_ignored"
    conflicting_accounts_flattened = "conflicting_accounts_flattened"
    unsupported_causal_link = "unsupported_causal_link"


class EvidenceRole(StrEnum):
    supporting = "supporting"
    contradicting = "contradicting"
    qualifying = "qualifying"


class WarningCode(StrEnum):
    section_not_processed = "section_not_processed"
    span_out_of_range = "span_out_of_range"
    ambiguous_speaker = "ambiguous_speaker"
    input_truncated = "input_truncated"
    other = "other"


class Status(StrEnum):
    complete = "complete"
    partial = "partial"


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Turn(_Model):
    id: str
    speaker: str
    role: Role | None = None
    text: str
    timestamp: str | None = None


class Section(_Model):
    id: str
    label: str | None = None
    score: float | str | None = None
    text: str


class AuditRequest(_Model):
    schema_version: Literal["1.1.0"]
    request_id: str | None = None
    transcript: list[Turn]
    assessment: list[Section]


class Pointer(_Model):
    index: int
    char: int


class Span(_Model):
    start: Pointer
    end: Pointer


class Evidence(_Model):
    id: str
    role: EvidenceRole
    span: Span
    note: str | None = None


class Concern(_Model):
    type: ConcernType
    explanation: str
    evidence_ids: list[str]


class Claim(_Model):
    id: str
    span: Span
    verdict: Verdict
    explanation: str
    out_of_scope_reason: str | None = None
    suggested_revision: str | None = None
    concerns: list[Concern]
    evidence: list[Evidence]


class Warning(_Model):  # noqa: A001 - contract name
    code: WarningCode
    message: str
    claim_id: str | None = None
    section_index: int | None = None


class AuditResponse(_Model):
    schema_version: Literal["1.1.0"] = "1.1.0"
    request_id: str | None = None
    status: Status
    warnings: list[Warning]
    claims: list[Claim]

    def to_json(self) -> dict:
        return self.model_dump(mode="json", exclude_none=True)
