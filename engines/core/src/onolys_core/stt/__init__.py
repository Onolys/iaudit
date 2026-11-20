"""Provider-neutral STT interface types (PRD R4). Adapters live in later tasks."""

from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, Protocol

from pydantic import BaseModel

if TYPE_CHECKING:
    from onolys_core.transcript import Transcript


class SttParams(BaseModel):
    provider: str
    model: str
    language: str = "auto"  # BCP-47 or "auto"
    diarization: bool = True
    speakers_min: int = 2
    speakers_max: int = 2
    options: dict = {}  # provider-only fields


class AudioRef(BaseModel):
    uri: str
    local_path_fn: Callable[[], Path] | None = None
    mime: str
    duration_ms: int | None = None


class Word(BaseModel):
    text: str
    start_ms: int
    end_ms: int
    speaker: str | None = None


class SttRun(BaseModel):
    provider: str
    model: str
    location: str | None = None
    language_requested: str
    language_detected: str | None = None
    adapter_version: str


class SttAdapter(Protocol):
    async def start(self, audio: AudioRef, params: SttParams) -> str:
        """Begin transcription; return an opaque, JSON-serialisable handle."""
        ...

    async def poll(self, handle: str) -> "Transcript | None":
        """Return the Transcript, or None while still running."""
        ...
