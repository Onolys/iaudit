"""FixtureVoice: deterministic audio, scripted events and failure injection (tests, previews)."""

import asyncio
import math
import struct
from collections.abc import AsyncIterator

from onolys_core.voice import (
    OUTPUT_SAMPLE_RATE,
    AudioOut,
    Closed,
    ResumptionHandle,
    TurnComplete,
    VoiceEvent,
    VoiceParams,
    VoiceProviderError,
)


def tone_pcm24k(ms: int = 100, freq_hz: float = 440.0, amplitude: int = 8000) -> bytes:
    """Deterministic 24 kHz mono PCM16 sine tone."""
    n = OUTPUT_SAMPLE_RATE * ms // 1000
    return b"".join(
        struct.pack("<h", int(amplitude * math.sin(2 * math.pi * freq_hz * i / OUTPUT_SAMPLE_RATE)))
        for i in range(n)
    )


def silence_pcm24k(ms: int = 100) -> bytes:
    return b"\x00\x00" * (OUTPUT_SAMPLE_RATE * ms // 1000)


def default_script() -> list[VoiceEvent]:
    return [
        AudioOut(tone_pcm24k(100)),
        AudioOut(silence_pcm24k(50)),
        TurnComplete(),
        ResumptionHandle("fixture-handle-1"),
    ]


class FixtureVoiceSession:
    def __init__(
        self,
        script: list[VoiceEvent],
        *,
        fail_send_after: int | None = None,
        fail_events_after: int | None = None,
    ):
        self._script = list(script)
        self._fail_send_after = fail_send_after
        self._fail_events_after = fail_events_after
        self._closed = asyncio.Event()
        self.sent: list[bytes] = []
        self.close_calls = 0

    async def send_audio(self, pcm16k: bytes) -> None:
        if self._closed.is_set():
            raise VoiceProviderError("session closed")
        if self._fail_send_after is not None and len(self.sent) >= self._fail_send_after:
            raise VoiceProviderError("injected send failure")
        self.sent.append(pcm16k)

    async def events(self) -> AsyncIterator[VoiceEvent]:
        for i, ev in enumerate(self._script):
            if self._closed.is_set():
                break
            if self._fail_events_after is not None and i >= self._fail_events_after:
                self._closed.set()
                raise VoiceProviderError("injected stream failure")
            yield ev
            if isinstance(ev, Closed):
                self._closed.set()
                return
        if not self._closed.is_set():
            await self._closed.wait()  # idle until the caller closes
        yield Closed("closed")

    async def close(self) -> None:
        self.close_calls += 1
        self._closed.set()


class FixtureVoice:
    """`VoiceAdapter` replaying `script` (default: a tone, silence, turn_complete, a handle)."""

    def __init__(
        self,
        script: list[VoiceEvent] | None = None,
        *,
        fail_open: bool = False,
        fail_send_after: int | None = None,
        fail_events_after: int | None = None,
    ):
        self._script = script if script is not None else default_script()
        self._fail_open = fail_open
        self._fail_send_after = fail_send_after
        self._fail_events_after = fail_events_after
        self.opened: list[VoiceParams] = []
        self.sessions: list[FixtureVoiceSession] = []

    async def open(self, params: VoiceParams) -> FixtureVoiceSession:
        if self._fail_open:
            raise VoiceProviderError("injected open failure")
        self.opened.append(params)
        session = FixtureVoiceSession(
            self._script,
            fail_send_after=self._fail_send_after,
            fail_events_after=self._fail_events_after,
        )
        self.sessions.append(session)
        return session
