"""Gemini Live on Vertex AI voice adapter (ai-interview PRD R3, D5-D7).

The only module that names this provider's SDK. `google-genai` (extra `voice-gemini`) is
imported lazily so `onolys_core.voice` works without it. Auth is Application Default
Credentials. Options: `location` (default us-central1), `project` (default: ADC project),
`context_window_compression` (default false). Session resumption is always on. The system
prompt is passed to the SDK and never logged.
"""

import contextlib
from collections.abc import AsyncIterator, Callable
from datetime import timedelta
from typing import Any

from onolys_core.safe_log import log_event
from onolys_core.voice import (
    AudioOut,
    Closed,
    GoAway,
    Interrupted,
    ResumptionHandle,
    TurnComplete,
    VoiceEvent,
    VoiceParams,
    VoiceProviderError,
)

DEFAULT_LOCATION = "us-central1"
INPUT_MIME = "audio/pcm;rate=16000"


def _default_client(options: dict) -> Any:
    try:
        from google import genai
    except ImportError as e:  # pragma: no cover - extra not installed
        raise VoiceProviderError("google-genai is not installed (extra voice-gemini)") from e
    return genai.Client(
        vertexai=True,
        project=options.get("project"),
        location=options.get("location", DEFAULT_LOCATION),
    )


def _seconds(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, timedelta):
        return value.total_seconds()
    try:
        return float(str(value).rstrip("s"))
    except ValueError:
        return None


def build_config(params: VoiceParams) -> Any:
    from google.genai import types

    cfg = dict(
        response_modalities=["AUDIO"],
        system_instruction=params.system_prompt,
        speech_config=types.SpeechConfig(
            voice_config=types.VoiceConfig(
                prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=params.voice)
            ),
            language_code=params.language,
        ),
        session_resumption=types.SessionResumptionConfig(handle=params.resumption_handle),
    )
    if params.options.get("context_window_compression"):
        cfg["context_window_compression"] = types.ContextWindowCompressionConfig(
            sliding_window=types.SlidingWindow()
        )
    return types.LiveConnectConfig(**cfg)


class GeminiLiveSession:
    def __init__(self, cm: Any, session: Any):
        self._cm = cm
        self._session = session
        self._closed = False

    async def send_audio(self, pcm16k: bytes) -> None:
        from google.genai import types

        if self._closed:
            raise VoiceProviderError("session closed")
        try:
            await self._session.send_realtime_input(
                audio=types.Blob(data=pcm16k, mime_type=INPUT_MIME)
            )
        except Exception as e:
            raise VoiceProviderError(f"send failed: {type(e).__name__}") from e

    def _map(self, msg: Any) -> list[VoiceEvent]:
        out: list[VoiceEvent] = []
        upd = getattr(msg, "session_resumption_update", None)
        if upd is not None and upd.new_handle and upd.resumable is not False:
            out.append(ResumptionHandle(upd.new_handle))
        if getattr(msg, "go_away", None) is not None:
            out.append(GoAway(_seconds(msg.go_away.time_left)))
        sc = getattr(msg, "server_content", None)
        if sc is not None:
            turn = getattr(sc, "model_turn", None)
            for part in (turn.parts or []) if turn else []:
                data = part.inline_data.data if part.inline_data else None
                if data:
                    out.append(AudioOut(bytes(data)))
            if getattr(sc, "interrupted", None):
                out.append(Interrupted())
            if getattr(sc, "turn_complete", None):
                out.append(TurnComplete())
        return out

    async def events(self) -> AsyncIterator[VoiceEvent]:
        reason = "closed"
        try:
            while not self._closed:
                seen = False
                async for msg in self._session.receive():
                    seen = True
                    for ev in self._map(msg):
                        yield ev
                if not seen:
                    reason = "upstream_ended"
                    break
        except Exception as e:
            reason = "closed" if self._closed else type(e).__name__
        yield Closed(reason)

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        with contextlib.suppress(Exception):
            await self._cm.__aexit__(None, None, None)


class GeminiLiveVertex:
    """`VoiceAdapter` for Gemini Live on Vertex. `client_factory(options)` is for tests."""

    def __init__(self, client_factory: Callable[[dict], Any] | None = None):
        self._client_factory = client_factory or _default_client

    async def open(self, params: VoiceParams) -> GeminiLiveSession:
        config = build_config(params)
        cm = None
        try:
            client = self._client_factory(params.options)
            cm = client.aio.live.connect(model=params.model, config=config)
            session = await cm.__aenter__()
        except VoiceProviderError:
            raise
        except Exception as e:
            raise VoiceProviderError(f"open failed: {type(e).__name__}") from e
        log_event(
            "voice_open",
            step="open",
            voice_provider=params.provider,
            voice_model=params.model,
            voice=params.voice,
            language=params.language,
            status="resumed" if params.resumption_handle else "new",
        )
        return GeminiLiveSession(cm, session)
