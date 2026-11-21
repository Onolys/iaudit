"""Provider-neutral realtime voice interface types (ai-interview PRD R3).

Adapters live in sibling modules; nothing here names a provider.
"""

from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Protocol

from pydantic import BaseModel

from onolys_core.errors import OnolysError
from onolys_core.safe_log import register_fields

# Loggable voice fields. The system prompt is never loggable (not allowlisted).
register_fields({"voice_provider", "voice_model", "voice", "reason", "frames"})

INPUT_SAMPLE_RATE = 16_000  # PCM16 mono, little-endian, from the client
OUTPUT_SAMPLE_RATE = 24_000  # PCM16 mono, little-endian, to the client


class VoiceProviderError(OnolysError):
    """The upstream voice provider failed (connect, send, auth). Carries no prompt text."""


class VoiceParams(BaseModel):
    provider: str
    model: str
    voice: str
    language: str = "en-US"  # BCP-47
    system_prompt: str = ""
    resumption_handle: str | None = None
    options: dict = {}  # provider-only fields

    def __repr_args__(self):
        # Keep the system prompt out of repr()/logs/tracebacks.
        for k, v in super().__repr_args__():
            yield k, ("<redacted>" if k == "system_prompt" else v)


@dataclass(frozen=True)
class AudioOut:
    pcm24k: bytes


@dataclass(frozen=True)
class Interrupted:
    """The user barged in: the client must flush queued AI audio."""


@dataclass(frozen=True)
class TurnComplete:
    pass


@dataclass(frozen=True)
class ResumptionHandle:
    h: str


@dataclass(frozen=True)
class GoAway:
    """The provider will drop this session soon; reopen with the latest handle."""

    time_left_s: float | None = None


@dataclass(frozen=True)
class Closed:
    reason: str  # short, content-free (e.g. "closed", "dropped", an exception class name)


VoiceEvent = AudioOut | Interrupted | TurnComplete | ResumptionHandle | GoAway | Closed


class VoiceSession(Protocol):
    async def send_audio(self, pcm16k: bytes) -> None: ...

    def events(self) -> AsyncIterator[VoiceEvent]:
        """Yield events until a final `Closed`, then stop."""
        ...

    async def close(self) -> None: ...


class VoiceAdapter(Protocol):
    async def open(self, params: VoiceParams) -> VoiceSession: ...
