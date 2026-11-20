"""FixtureStt: replays recorded word lists keyed by audio-uri hash (tests, api stub, CI)."""

import hashlib

from onolys_core.errors import InputError
from onolys_core.stt import AudioRef, SttParams, SttRun, Word
from onolys_core.stt.base import BaseSttAdapter

ADAPTER_VERSION = "fixture-1"


def uri_hash(uri: str) -> str:
    return hashlib.sha256(uri.encode("utf-8")).hexdigest()


class FixtureStt(BaseSttAdapter):
    def __init__(self, fixtures: dict[str, list[Word]], *, polls_before_ready: int = 0):
        """`fixtures` maps `uri_hash(uri)` to the word list to replay."""
        self._fixtures = fixtures
        self._polls_before_ready = polls_before_ready
        self._jobs: dict[str, tuple[str, str, int]] = {}  # handle -> (hash, lang, polls)
        self.submits = 0

    async def _submit(self, audio: AudioRef, params: SttParams) -> str:
        h = uri_hash(audio.uri)
        if h not in self._fixtures:
            raise InputError(f"no STT fixture for audio uri {audio.uri!r}")
        self.submits += 1
        handle = f"fixture:{h}:{self.submits}"
        self._jobs[handle] = (h, params.language, 0)
        return handle

    async def _fetch(self, handle: str) -> tuple[list[Word], SttRun] | None:
        if handle not in self._jobs:
            raise InputError(f"unknown STT handle {handle!r}")
        h, lang, polls = self._jobs[handle]
        if polls < self._polls_before_ready:
            self._jobs[handle] = (h, lang, polls + 1)
            return None
        run = SttRun(
            provider="fixture",
            model="fixture",
            language_requested=lang,
            adapter_version=ADAPTER_VERSION,
        )
        return [w.model_copy() for w in self._fixtures[h]], run
