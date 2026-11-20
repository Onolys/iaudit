"""Internal draft models produced by stages 03-06 and consumed by the assembler.

Drafts carry verbatim text, never offsets. The report holds counts only.
"""

from collections import Counter
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from eaudit.models import ConcernType, EvidenceRole, Verdict


class AssemblyError(RuntimeError):
    """Final validation failed; SP01 maps this to internal_error (500)."""


class _Draft(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ExcerptSegment(_Draft):
    turn_index: int
    text: str
    char_hint: int | None = None


class EvidenceDraft(_Draft):
    key: str
    role: EvidenceRole
    segments: list[ExcerptSegment]
    note: str | None = None


class ConcernDraft(_Draft):
    type: ConcernType
    explanation: str
    evidence_keys: list[str] = Field(default_factory=list)


class Outcome(StrEnum):
    ok = "ok"
    stalled = "stalled"


class ClaimDraft(_Draft):
    key: str
    section_index: int
    segments: list[str]
    span_hint: tuple[int, int] | None = None
    outcome: Outcome = Outcome.ok
    verdict: Verdict
    explanation: str
    out_of_scope_reason: str | None = None
    suggested_revision: str | None = None
    concerns: list[ConcernDraft] = Field(default_factory=list)
    evidence: list[EvidenceDraft] = Field(default_factory=list)
    ambiguous_turns: list[int] = Field(default_factory=list)


class SectionFailure(_Draft):
    section_index: int
    reason: Literal["timeout", "error"]


class InternalAudit(_Draft):
    claims: list[ClaimDraft] = Field(default_factory=list)
    section_failures: list[SectionFailure] = Field(default_factory=list)
    truncated: bool = False


class AssembleReport(BaseModel):
    """Counts only. Never holds transcript or assessment text."""

    evidence_tiers: Counter[str] = Field(default_factory=Counter)
    evidence_scores: list[float] = Field(default_factory=list)
    claim_tiers: Counter[str] = Field(default_factory=Counter)
    occurrences: list[int] = Field(default_factory=list)
    drops: Counter[str] = Field(default_factory=Counter)
    repairs: Counter[str] = Field(default_factory=Counter)

    def drop(self, reason: str) -> None:
        self.drops[reason] += 1

    def repair(self, code: str) -> None:
        self.repairs[code] += 1


class AssembleOutcome(BaseModel):
    response: dict
    report: AssembleReport
