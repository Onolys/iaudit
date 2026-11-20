"""Engine adapters: the only seam to the engines (PRD R6). `ADAPTERS=stub|real`."""

from dataclasses import dataclass

from onolys_core.errors import ConfigError
from onolys_core.stt.fixture import FixtureStt

from onolys_api.adapters.base import (
    AdapterError,
    Evaluation,
    EvaluationOutput,
    ProgressCb,
    Stage,
    StageStatus,
    Stt,
)
from onolys_api.adapters.fake import FakeEvaluation, FakeStt
from onolys_api.config import Settings

__all__ = [
    "AdapterError", "Adapters", "Evaluation", "EvaluationOutput", "FakeEvaluation", "FakeStt",
    "FixtureStt", "ProgressCb", "Stage", "StageStatus", "Stt", "build_adapters",
]  # fmt: skip


@dataclass(frozen=True)
class Adapters:
    stt: Stt
    evaluation: Evaluation


def build_adapters(settings: Settings) -> Adapters:
    if settings.adapters == "stub":
        return Adapters(stt=FakeStt(), evaluation=FakeEvaluation())
    raise ConfigError("ADAPTERS=real is not available yet: the real engine adapters land in SP09")
