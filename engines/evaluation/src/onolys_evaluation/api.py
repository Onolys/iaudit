"""Public function signatures (SP03 R1). Bodies land in later tasks; they raise until then."""

from collections.abc import Callable
from typing import Any, Literal

from eaudit.models import AuditResponse
from onolys_core.engine import RunContext
from onolys_core.transcript import Transcript
from paudit.pack import Pack
from paudit.result import PauditResult
from pydantic import BaseModel

from onolys_evaluation.rating import is_no_rating, validate_rating  # noqa: F401
from onolys_evaluation.report import Report, Tip

Stage = Literal["paudit", "eaudit", "tips", "compare", "assemble"]
StageStatus = Literal["started", "done", "failed"]
ProgressCb = Callable[[Stage, StageStatus], None]


class TipsArtifact(BaseModel):
    """Validated tips plus the raw model proposals (for audit; never shown to users)."""

    valid: list[Tip]
    proposals: list[dict[str, Any]]


class Artifacts(BaseModel):
    paudit: PauditResult
    eaudit: AuditResponse | None = None
    tips: TipsArtifact | None = None


class EvaluationOutput(BaseModel):
    """The report plus run artifacts. `run_info` is `report.run_info`."""

    report: Report
    artifacts: Artifacts


async def run_evaluation(
    ctx: RunContext,
    pack: Pack,
    transcript: Transcript,
    speaker_map: dict[str, str],
    params: dict[str, Any],
    rating: dict[str, Any] | None,
    paudit_result: PauditResult | None,
    progress_cb: ProgressCb | None = None,
) -> EvaluationOutput:
    """R1: the whole `running` phase (paudit, reasons audit, tips, compare, assemble)."""
    raise NotImplementedError("SP03 later task")


def build_report(*args: Any, **kwargs: Any) -> Report:
    """R1: pure assembly from already-computed parts."""
    raise NotImplementedError("SP03 later task")
