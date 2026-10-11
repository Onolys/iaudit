"""Stage 1 models: what the atomizer LLM returns (`RawClaim`) and what 04/05/02 consume."""

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, computed_field, field_validator, model_validator

from iaudit_backend.scales import FrequencyBucket, SeverityBucket


class OosCategory(StrEnum):
    diagnostic_conclusion = "diagnostic_conclusion"
    scoring_rule = "scoring_rule"
    recommendation = "recommendation"
    unobservable = "unobservable"
    external_criteria = "external_criteria"


# The LLM picks the category; code owns the sentence (contract rule 9: no copied text).
OOS_REASONS: dict[OosCategory, str] = {
    OosCategory.diagnostic_conclusion: (
        "This is a diagnostic conclusion; the audit does not check whether behaviors meet a "
        "criterion."
    ),
    OosCategory.scoring_rule: (
        "This restates a score or scoring rule, which the audit does not check."
    ),
    OosCategory.recommendation: (
        "This is a recommendation, not a factual claim about the interview."
    ),
    OosCategory.unobservable: (
        "This describes an observation made outside the supplied interview, which cannot be "
        "checked."
    ),
    OosCategory.external_criteria: (
        "This depends on external criteria that are not in the supplied interview."
    ),
}

Source = Literal["self", "informant", "interviewer", "assessor", "unspecified"]
Timeframe = Literal["current", "past", "childhood", "future", "hypothetical", "unspecified"]
_BUCKETS = {"frequency": FrequencyBucket, "severity": SeverityBucket}


class _M(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ReportedBy(_M):
    source: Source
    speaker: str | None = None


class Quantity(_M):
    kind: Literal["frequency", "severity"]
    raw: str
    bucket: str | None = None
    rate_per_week: float | None = None

    @model_validator(mode="after")
    def _bucket_matches_kind(self) -> "Quantity":
        # The schema leaves `bucket` free text. A wrong-scale guess is dropped, not an error:
        # scales.resolve_quantity works the bucket out from `raw`.
        if self.bucket is not None and self.bucket not in _BUCKETS[self.kind].__members__:
            self.bucket = None
        return self


class CausalLink(_M):
    type: Literal["causal"] = "causal"
    cause_ids: list[str] = Field(min_length=1)
    effect_id: str
    connector: str
    source: Literal["assessor", "reported"]


class _ClaimFields(_M):
    segments: list[str] = Field(min_length=1, max_length=3)
    proposition: str
    scope: Literal["in_scope", "out_of_scope"]
    oos_category: OosCategory | None = None
    subject_text: str
    subject_speaker: str | None = None
    reported_by: list[ReportedBy] = Field(min_length=1)
    polarity: Literal["affirmed", "negated"]
    quantities: list[Quantity] = Field(default_factory=list, max_length=2)
    timeframe: Timeframe
    timeframe_explicit: bool
    hedged: bool

    @field_validator("segments")
    @classmethod
    def _non_blank(cls, v: list[str]) -> list[str]:
        if any(not s.strip() for s in v):
            raise ValueError("segments must be non-blank")
        return v


class RawClaim(_ClaimFields):
    """One claim as the LLM writes it. `ref` is a local label that links point at."""

    ref: str


class AtomizerOutput(_M):
    claims: list[RawClaim]
    links: list[CausalLink] = Field(default_factory=list)


class AtomicClaim(_ClaimFields):
    id: str  # c{section}.{n}, document order
    section_index: int
    span_hint: tuple[int, int] | None = None  # code points in the section, set by 03
    span_quality: Literal["covering", "anchor_only"] | None = None  # 03-internal

    @model_validator(mode="after")
    def _category_iff_out_of_scope(self):
        if (self.scope == "out_of_scope") != (self.oos_category is not None):
            raise ValueError("oos_category is set iff scope is out_of_scope")
        return self

    @computed_field
    @property
    def oos_reason(self) -> str | None:
        return OOS_REASONS[self.oos_category] if self.oos_category else None


class SectionAtoms(_M):
    """Result for one assessment section. A failed section never carries guessed claims."""

    section_index: int
    status: Literal["ok", "failed"]
    claims: list[AtomicClaim] = Field(default_factory=list)
    links: list[CausalLink] = Field(default_factory=list)
    dropped: int = 0
    coverage_gaps: int = 0
    retries: int = 0
    failure: (
        Literal["timeout", "unavailable", "bad_output", "no_claims", "too_many_dropped"] | None
    ) = None
