"""Stage 3 models: what the verifier LLM observes, and the internal judged state."""

from dataclasses import dataclass, field
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from eaudit.atomize.models import Timeframe
from eaudit.link.models import LinkedEvidence
from eaudit.models import ConcernType, EvidenceRole, Verdict

Conf = Literal["low", "medium", "high"]
CONF_VALUE: dict[str, float] = {"low": 0.3, "medium": 0.6, "high": 0.9}
Relation = Literal["entails", "contradicts", "not_addresses"]
Experiencer = Literal["claim_subject", "other_person", "unclear"]
FlagType = Literal[
    "timeframe_mismatch",
    "certainty_inflation",
    "context_stripping",
    "correction_ignored",
    "conflicting_accounts_flattened",
    "unsupported_causal_link",
    "element_gap",
    "quantity_mismatch",
]
StallReason = Literal["timeout", "unavailable", "bad_output"]


class _M(BaseModel):
    model_config = ConfigDict(extra="forbid")


class QuantityObs(_M):
    """An amount the evidence states. Code maps it to a bucket; `bucket_guess` is a last resort."""

    raw: str
    rate_per_week: float | None = None
    bucket_guess: str | None = None
    basis: Literal["numeric", "relative"] = "relative"


class ItemObs(_M):
    key: str
    relation: Relation
    polarity: Literal["affirmed", "negated", "unclear"] = "unclear"
    frequency: list[QuantityObs] = Field(default_factory=list, max_length=3)
    severity: list[QuantityObs] = Field(default_factory=list, max_length=3)
    timeframe: Timeframe = "unspecified"
    certainty: Literal["definite", "hedged_light", "hedged_strong"] = "definite"
    experiencer: Experiencer = "claim_subject"
    conf: Conf = "medium"


class FlagObs(_M):
    type: FlagType
    keys: list[str] = Field(default_factory=list)
    conf: Conf = "medium"


class InferenceObs(_M):
    key: str
    step_acceptable: bool
    conf: Conf = "medium"


class VerifierOutput(_M):
    items: list[ItemObs]
    flags: list[FlagObs] = Field(default_factory=list)
    inferences: list[InferenceObs] = Field(default_factory=list)
    suggested_revision: str | None = None


@dataclass
class JudgedEvidence:
    """One evidence item with the verifier's observation and the code-side checks on it."""

    key: str
    linked: LinkedEvidence
    obs: ItemObs | None = None  # None: unjudged or below the confidence floor
    turns: list[int] = field(default_factory=list)
    endorsed: bool = True
    attribution: Literal["ok", "mismatch", "skip"] = "ok"
    demote: str | None = None  # "timeframe" | "inference"
    cited: bool = False  # cited by an accepted 8/10/12 flag: counts as partial support
    escalated: bool = False  # amount gap made it a contradiction
    speakers: list[str] = field(default_factory=list)  # who said the cited turns


@dataclass
class Signals:
    flags: list[FlagObs] = field(default_factory=list)  # accepted (above floor), keys known
    failed_inference: bool = False
    counts: dict[str, int] = field(default_factory=dict)


@dataclass
class Concern:
    type: ConcernType
    keys: list[str] = field(default_factory=list)
    direction: str | None = None  # "inflates" | "understates" for amount concerns
    scale: str | None = None  # "frequency" | "severity"


@dataclass
class Decision:
    verdict: Verdict
    concerns: list[Concern] = field(default_factory=list)
    roles: dict[str, EvidenceRole] = field(default_factory=dict)  # emitted items only
    row: str = ""
    counts: dict[str, int] = field(default_factory=dict)
