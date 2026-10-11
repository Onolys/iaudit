"""Stage 2 models: what the linker LLM returns and what 05/02 consume."""

from dataclasses import dataclass, field
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from iaudit_backend.assembler.models import EvidenceDraft
from iaudit_backend.models import EvidenceRole


class _M(BaseModel):
    model_config = ConfigDict(extra="forbid")


class LinkerSegment(_M):
    turn: int
    text: str


class LinkerItem(_M):
    """One piece of evidence as the LLM writes it. Cross-field rules are checked in code."""

    key: str
    role: EvidenceRole
    link_type: Literal["quote", "paraphrase", "inference"]
    segments: list[LinkerSegment] = Field(default_factory=list)
    premises: list[str] = Field(default_factory=list)  # keys of other items; inference only
    inference_step: str | None = None
    note: str | None = None


class LinkerOutput(_M):
    items: list[LinkerItem]


AnswerStatus = Literal["endorsed", "question_only", "non_answer", "n/a"]


@dataclass
class LinkedEvidence:
    draft: EvidenceDraft  # 02's model; keys are "{claim.id}:e{n}"
    link_type: str
    premise_keys: list[str] = field(default_factory=list)  # internal to 04/05
    inference_step: str | None = None  # internal, never emitted
    answer_status: str = "n/a"


@dataclass
class LinkResult:
    claim_id: str
    status: Literal["ok", "stalled"] = "ok"
    reason: str | None = None  # timeout | unavailable | bad_output | all_dropped
    mode: str = "shortlist"
    shortlist: list[int] = field(default_factory=list)
    evidence: list[LinkedEvidence] = field(default_factory=list)
    ambiguous_turns: list[int] = field(default_factory=list)
    counts: dict[str, int] = field(default_factory=dict)  # drops/coerced/retries, counts only
