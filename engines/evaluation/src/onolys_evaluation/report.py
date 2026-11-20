"""Typed report (SP03 R7). `schemas/report.schema.json` is generated from these models
(`python -m onolys_evaluation.report --write`); a test keeps the two in sync. SP04 validates stored
reports against the schema and SP05 generates its TypeScript types from it.

Protocol-agnostic: item ids, summary ids and section ids are free strings defined by the pack.
Quotes are copied into the report with `{turn_id, start, end}` (code-point offsets into the turn's
text), so a report is self-contained."""

import json
import sys
from pathlib import Path
from typing import Annotated, Any, Literal

from onolys_core.run_info import RunInfo
from onolys_core.stt import SttRun
from paudit.result import WarningCode
from pydantic import BaseModel, ConfigDict, Field, model_validator

SCHEMA_VERSION = "0.0.1"

# Engine-defined warning codes; paudit warnings pass through and packs may add more.
WARNING_CODES = (
    "reasons_audit_failed",
    "reasons_audit_partial",
    "tips_failed",
    "fewer_tips",
)

Offset = Annotated[int, Field(ge=0)]
DiffStatus = Literal["agree", "differs", "flagged", "not_rated", "no_onolys_value"]
ClaimVerdict = Literal[
    "supported", "partially_supported", "contradicted", "insufficient_evidence", "out_of_scope"
]
EvidenceRole = Literal["supporting", "contradicting", "qualifying"]
ReasonsAuditStatus = Literal["ran", "partial", "skipped", "failed"]
Label = Literal["below_fair", "fair", "good"]


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Issue(_Model):
    """One `validate_rating` problem: a path into the rating card and a code, never any text."""

    path: str
    code: str


class Warning(_Model):  # noqa: A001 - name from the PRD
    code: WarningCode = Field(
        json_schema_extra={"examples": list(WARNING_CODES)},
        description="Engine code (see WARNING_CODES), a paudit code, or a pack-defined code.",
    )
    item_id: str | None = None


class Line(_Model):
    """A quote located in a turn. `start`/`end` are code-point offsets into the turn's text."""

    turn_id: str
    start: Offset
    end: Offset
    quote: str

    @model_validator(mode="after")
    def _check(self):
        if self.end < self.start:
            raise ValueError("end < start")
        return self


class Instance(Line):
    id: str
    rationale: str


class AuditEvidence(Line):
    role: EvidenceRole


class Protocol(_Model):
    id: str
    version: str
    pack_hash: str
    label: str


class CodedSpan(_Model):
    from_s: float | None = None
    to_s: float | None = None


class RatingCoverage(_Model):
    rated: Annotated[int, Field(ge=0)]
    total: Annotated[int, Field(ge=0)]


class Header(_Model):
    change_goal: str
    protocol: Protocol
    language: str
    coded_span: CodedSpan | None
    subject_speaker: str
    n_runs: Annotated[int, Field(ge=1)]
    models: dict[str, str] = Field(description="route name -> litellm id")
    stt: SttRun | None = Field(description="The transcript's typed SttRun; null for text-only.")
    preset: str | None
    code_version: str
    params: dict[str, Any]
    has_clinician_rating: bool
    rating_coverage: RatingCoverage


class LayoutEntry(_Model):
    section: str
    title: str
    items: list[str] | None = None


class Diff(_Model):
    signed: float | None
    abs: float | None
    direction: str | None
    status: DiffStatus
    within_one: bool | None = None


class RunStats(_Model):
    mean: float | None
    min: float | None
    max: float | None
    values: list[float]


class ClinicianValue(_Model):
    value: float | None


class OnolysScoreStats(RunStats):
    value: float | None


class ScorecardRow(_Model):
    item_id: str
    kind: Literal["global", "count"]
    label: str
    clinician: ClinicianValue
    onolys: OnolysScoreStats
    diff: Diff


class Explanation(_Model):
    headline: str
    body: list[str]
    onolys_lines: list[Line]
    clinician_support_lines: list[Line]


class OnolysGlobal(_Model):
    score: int | None
    source: Literal["model", "default", "capped"] | None
    reason: str | None = None
    evidence: list[Line]


class ClinicianExample(_Model):
    at_s: float | None = None
    text: str


class ClinicianGlobal(_Model):
    value: int | None
    reason: str | None = None
    example: ClinicianExample | None = None


class GlobalEntry(_Model):
    item_id: str
    onolys: OnolysGlobal
    clinician: ClinicianGlobal
    diff: Diff
    explanation: Explanation


class BehaviourEntry(_Model):
    item_id: str
    clinician_count: int | None
    clinician_note: str | None = None
    onolys_count: RunStats
    instances: list[Instance]
    instances_total: Annotated[int, Field(ge=0)]
    diff: Diff
    explanation: Explanation


class SummaryReference(_Model):
    fair: float
    good: float


class SummaryValue(_Model):
    value: float | None
    label: Label | None


class SummaryEntry(_Model):
    id: str
    label: str
    clinician: SummaryValue | None
    onolys: SummaryValue
    reference: SummaryReference | None
    note: str


class AuditClaim(_Model):
    span: str = Field(description="The claim text as written in the clinician's reason.")
    verdict: ClaimVerdict
    explanation: str
    concerns: list[str]
    evidence: list[AuditEvidence]


class AuditItem(_Model):
    item_id: str = Field(description="Pack item id, or `notes` for the additional-notes box.")
    reason: str
    claims: list[AuditClaim]


class ReasonsAudit(_Model):
    status: ReasonsAuditStatus
    items: list[AuditItem]


class TipQuote(_Model):
    turn_id: str
    start: Offset
    end: Offset
    text: str

    @model_validator(mode="after")
    def _check(self):
        if self.end < self.start:
            raise ValueError("end < start")
        return self


class Tip(_Model):
    rank: Annotated[int, Field(ge=1)]
    item_id: str
    observation: str
    quote: TipQuote
    alternative: str
    why_it_matters: str


class Method(_Model):
    statement: str
    limits: list[str]
    not_official_miti_coding: Literal[True]
    citation: str


class Aggregates(_Model):
    globals_compared: Annotated[int, Field(ge=0)]
    avg_abs_global_difference: float | None
    within_one_share: float | None
    counts_flagged: int | None


class ReportRunInfo(_Model):
    evaluation: RunInfo
    paudit: RunInfo
    eaudit: RunInfo | None = Field(description="null when no reasons audit ran.")


class Report(_Model):
    schema_version: Literal["0.0.1"]
    request_id: str | None = None
    created_at: str
    header: Header
    layout: list[LayoutEntry]
    scorecard: list[ScorecardRow]
    globals: list[GlobalEntry]
    behaviours: list[BehaviourEntry]
    summaries: list[SummaryEntry]
    reasons_audit: ReasonsAudit
    tips: list[Tip]
    method: Method
    aggregates: Aggregates
    warnings: list[Warning]
    run_info: ReportRunInfo


def report_schema() -> dict[str, Any]:
    schema = Report.model_json_schema(mode="validation")
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": "Report",
        **schema,
    }


def schema_text() -> str:
    return json.dumps(report_schema(), indent=2) + "\n"


def schema_path() -> Path:
    here = Path(__file__).resolve()
    for cand in (here.parent / "schemas", here.parents[2] / "schemas"):
        if cand.is_dir():
            return cand / "report.schema.json"
    raise FileNotFoundError("schemas dir not found")


if __name__ == "__main__":
    if "--write" in sys.argv:
        schema_path().write_text(schema_text())
    else:
        sys.stdout.write(schema_text())
