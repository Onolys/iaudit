"""Engine interface (PRD R6)."""

from dataclasses import dataclass
from typing import Any, Protocol

from pydantic import BaseModel

from onolys_core.transcript import Transcript


class PackRef(BaseModel):
    id: str
    version: str
    path: str  # SP02 defines pack contents


class EngineResult(BaseModel):
    result: BaseModel
    # RunInfo lands in a later core task; typed as BaseModel until then.
    run_info: BaseModel


@dataclass
class RunContext:
    # `llm` (LLMClient) and `metrics` (MetricsCollector) land in a later core task.
    llm: Any
    metrics: Any
    request_id: str
    deadline: float | None = None


class Engine(Protocol):
    name: str  # "eaudit" | "paudit" | "caudit"

    async def run(
        self,
        transcript: Transcript,
        pack: PackRef | None,
        params: dict,
        ctx: RunContext,
    ) -> EngineResult: ...
