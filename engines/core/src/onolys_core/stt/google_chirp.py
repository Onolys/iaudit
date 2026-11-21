"""Google Speech-to-Text v2 (Chirp 3) adapter (PRD R4, D9).

`BatchRecognize` standard recognition, inline response, words only. The `google-cloud-speech`
package (extra `stt-google`) is imported lazily so `onolys_core.stt` works without it. Auth is
ADC; no keys in code. Real behaviour is proven by the live check (Task 13), not by unit tests.
"""

import asyncio
import json
from datetime import timedelta
from typing import Any, Protocol

from onolys_core.errors import InputError, OnolysError
from onolys_core.stt import AudioRef, SttParams, SttRun, Word
from onolys_core.stt.base import BaseSttAdapter

ADAPTER_VERSION = "google-chirp3-1"
DEFAULT_LOCATION = "us"
GLOBAL_ENDPOINT = "speech.googleapis.com"
_MS = timedelta(milliseconds=1)


class SttProviderError(OnolysError):
    """The provider reported a failed STT operation."""


def location_endpoint(location: str) -> str:
    """`us` -> `us-speech.googleapis.com`; `global` -> `speech.googleapis.com`."""
    return GLOBAL_ENDPOINT if location == "global" else f"{location}-{GLOBAL_ENDPOINT}"


def resolve_location(params: SttParams) -> tuple[str, str]:
    """Return (location, endpoint); an explicit `options.endpoint` wins over the derived one."""
    location = params.options.get("location") or DEFAULT_LOCATION
    return location, params.options.get("endpoint") or location_endpoint(location)


def build_batch_request(audio: AudioRef, params: SttParams, project: str) -> dict:
    """Pure request builder (dict form accepted by `SpeechClient.batch_recognize`)."""
    if not audio.uri.startswith("gs://"):
        raise InputError(f"Chirp 3 batch needs a gs:// audio uri, got {audio.uri!r}")
    if params.diarization and not 1 <= params.speakers_min <= params.speakers_max:
        raise InputError(
            f"invalid speaker bounds min={params.speakers_min} max={params.speakers_max}"
        )
    location, _ = resolve_location(params)
    features: dict[str, Any] = {
        "enable_word_time_offsets": True,
        "enable_automatic_punctuation": True,
    }
    if params.diarization:
        features["diarization_config"] = {
            "min_speaker_count": params.speakers_min,
            "max_speaker_count": params.speakers_max,
        }
    return {
        "recognizer": f"projects/{project}/locations/{location}/recognizers/_",
        "config": {
            "auto_decoding_config": {},
            "model": params.model,
            "language_codes": ["auto" if params.language == "auto" else params.language],
            "features": features,
        },
        "files": [{"uri": audio.uri}],
        "recognition_output_config": {"inline_response_config": {}},
    }


class GoogleBackend(Protocol):
    def submit(self, request: dict, endpoint: str) -> str:
        """Start BatchRecognize; return the long-running operation name."""

    def get(self, name: str, endpoint: str) -> Any | None:
        """Return the BatchRecognizeResponse, or None while the operation runs. Raises on error."""

    def project(self) -> str: ...


class _SdkBackend:
    """Real client; imports google lazily."""

    def _client(self, endpoint: str):
        try:
            from google.api_core.client_options import ClientOptions
            from google.cloud.speech_v2 import SpeechClient
        except ImportError as e:  # pragma: no cover - depends on the extra
            raise OnolysError(
                "google-cloud-speech is not installed; install the `stt-google` extra"
            ) from e
        return SpeechClient(client_options=ClientOptions(api_endpoint=endpoint))

    def project(self) -> str:
        import google.auth

        _, project = google.auth.default()
        if not project:
            raise InputError("no Google project: set options.project or the ADC quota project")
        return project

    def submit(self, request: dict, endpoint: str) -> str:
        return self._client(endpoint).batch_recognize(request=request).operation.name

    def get(self, name: str, endpoint: str) -> Any | None:
        from google.cloud.speech_v2 import BatchRecognizeResponse

        op = self._client(endpoint).get_operation({"name": name})
        if not op.done:
            return None
        if op.HasField("error"):
            raise SttProviderError(f"STT operation {name} failed: {op.error.message}")
        return BatchRecognizeResponse.deserialize(op.response.value)


def _ms(offset: Any) -> int:
    if isinstance(offset, timedelta):
        return offset // _MS
    return int(offset.seconds * 1000 + offset.nanos // 1_000_000)  # protobuf Duration


def extract_words(response: Any) -> tuple[list[Word], str | None]:
    """Words (speaker labels, ms offsets) from a BatchRecognizeResponse; never invents any."""
    words: list[Word] = []
    detected: str | None = None
    for uri, file_result in response.results.items():
        err = getattr(file_result, "error", None)
        if err is not None and getattr(err, "code", 0):
            raise SttProviderError(f"STT failed for {uri}: {err.message}")
        for res in file_result.transcript.results:
            if not res.alternatives:
                continue
            detected = detected or (res.language_code or None)
            for w in res.alternatives[0].words:
                words.append(
                    Word(
                        text=w.word,
                        start_ms=_ms(w.start_offset),
                        end_ms=_ms(w.end_offset),
                        speaker=w.speaker_label or None,
                    )
                )
    _clamp_ends(words)
    return words, detected


def _clamp_ends(words: list[Word]) -> None:
    """Chirp sometimes returns end=0 (or end < start). Use the next word's start when it is
    >= this word's start, else this word's start. Order is never changed."""
    for i, w in enumerate(words):
        if w.end_ms >= w.start_ms:
            continue
        nxt = words[i + 1].start_ms if i + 1 < len(words) else w.start_ms
        w.end_ms = nxt if nxt >= w.start_ms else w.start_ms


class GoogleChirp3(BaseSttAdapter):
    def __init__(self, backend: GoogleBackend | None = None):
        self._backend = backend or _SdkBackend()

    async def _submit(self, audio: AudioRef, params: SttParams) -> str:
        location, endpoint = resolve_location(params)
        project = params.options.get("project") or await asyncio.to_thread(self._backend.project)
        request = build_batch_request(audio, params, project)
        name = await asyncio.to_thread(self._backend.submit, request, endpoint)
        return json.dumps(
            {
                "op": name,
                "endpoint": endpoint,
                "location": location,
                "model": params.model,
                "lang": params.language,
            }
        )

    async def _fetch(self, handle: str) -> tuple[list[Word], SttRun] | None:
        try:
            h = json.loads(handle)
            name, endpoint = h["op"], h["endpoint"]
        except (ValueError, KeyError, TypeError) as e:
            raise InputError(f"bad Google STT handle {handle!r}") from e
        response = await asyncio.to_thread(self._backend.get, name, endpoint)
        if response is None:
            return None
        words, detected = extract_words(response)
        run = SttRun(
            provider="google",
            model=h.get("model", "chirp_3"),
            location=h.get("location"),
            language_requested=h.get("lang", "auto"),
            language_detected=detected,
            adapter_version=ADAPTER_VERSION,
        )
        return words, run
