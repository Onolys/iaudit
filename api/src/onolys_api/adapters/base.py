"""The only seam to the engines (PRD R6, D2, D20): exactly two Protocols, `Stt` and `Evaluation`.

`Stt` is the provider-neutral SP01 `SttAdapter` (`start`/`poll`); `Evaluation` wraps SP03
`run_evaluation` (one call runs the whole `running` phase, asyncio inside). There are no
per-stage adapters. Fake implementations live in `fake.py`; real ones are SP09.
"""

from collections.abc import Callable
from typing import Any, Literal, Protocol

from onolys_core.engine import PackRef, RunContext
from onolys_core.errors import OnolysError
from onolys_core.stt import AudioRef, SttParams
from onolys_core.transcript import Transcript
from pydantic import BaseModel, Field

Stage = Literal["paudit", "eaudit", "tips", "compare", "assemble"]
StageStatus = Literal["started", "done", "failed"]
ProgressCb = Callable[[Stage, StageStatus], None]


class AdapterError(OnolysError):
    """An engine call failed. `code` is a stable machine code; the caller maps it to a public
    error code (real mapping: SP09). Never carries transcript or rating text."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class EvaluationOutput(BaseModel):
    """SP03 `EvaluationOutput`: the report JSON (incl. its `run_info`) plus run artifacts."""

    report: dict[str, Any]
    artifacts: dict[str, Any] = Field(default_factory=dict)  # paudit, eaudit, tips


class Stt(Protocol):
    async def start(self, audio: AudioRef, params: SttParams) -> str:
        """Begin transcription once; return an opaque, JSON-serialisable handle."""
        ...

    async def poll(self, handle: str) -> Transcript | None:
        """Return the Transcript, or None while still running. Never re-submits."""
        ...


class Evaluation(Protocol):
    async def run(
        self,
        ctx: RunContext,
        pack: PackRef | None,
        transcript: Transcript,
        speaker_map: dict[str, str],
        params: dict[str, Any],
        rating: dict[str, Any] | None,
        progress_cb: ProgressCb | None = None,
    ) -> EvaluationOutput:
        """`speaker_map = {"subject": <transcript speaker label>}`. `params` =
        {change_goal, coded_span{from_s,to_s}, language, n_runs, preset, code_version}.
        Raises AdapterError when the run fails (paudit failure)."""
        ...
