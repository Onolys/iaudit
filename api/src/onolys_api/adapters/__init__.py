"""Engine adapters: the only seam to the engines (PRD R6). `ADAPTERS=stub|real`."""

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

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


def build_adapters(
    settings: Settings,
    *,
    stt_registry: Mapping[str, Callable[[], Any]] | None = None,
    llm_factory: Callable[[dict], Any] | None = None,
) -> Adapters:
    """`ADAPTERS=stub` -> fakes; `real` -> the SP09 adapters. The keyword hooks (a provider
    registry, an LLM client factory) let tests run the real wiring with fixture STT/LLM."""
    if settings.adapters == "stub":
        return Adapters(stt=FakeStt(), evaluation=FakeEvaluation())
    from onolys_api.adapters.real import RealEvaluation, RealStt

    evaluation = RealEvaluation(llm_factory=llm_factory) if llm_factory else RealEvaluation()
    return Adapters(stt=RealStt(stt_registry), evaluation=evaluation)
