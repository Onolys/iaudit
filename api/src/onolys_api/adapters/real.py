"""Real `Stt` adapter (SP09 R1, D5): a registry over the SP01 core STT adapters.

The provider is data: the worker passes the session's stored `stt.provider` in `SttParams`, and
this module looks the core adapter up by that key. There is no `if provider == ...` in worker
code. A new STT provider is one core adapter plus one `DEFAULT_REGISTRY` line (and its
`stt_providers.yaml` entry).

`poll(handle)` carries no provider, so `start` wraps the core handle as
`{"provider", "handle"}` JSON; `stt_operation` stores that string and `poll` routes on it.
The `Transcript` (incl. `stt_run`) from the core adapter is returned unchanged.

An unknown provider raises core `ConfigError` (an `OnolysError`): `error_map.to_public` maps it
to `internal_error`, not retryable, and the worker logs the class, never the message.
"""

import json
from collections.abc import Callable, Mapping

from onolys_core.errors import ConfigError
from onolys_core.stt import AudioRef, SttAdapter, SttParams
from onolys_core.stt.fixture import FixtureStt
from onolys_core.stt.google_chirp import GoogleChirp3
from onolys_core.transcript import Transcript

SttFactory = Callable[[], SttAdapter]

# provider key (stored on the session from stt_providers.yaml) -> core adapter factory.
# `google` is the value the packaged stt_providers.yaml writes for its Chirp 3 entry.
DEFAULT_REGISTRY: dict[str, SttFactory] = {
    "google_chirp": GoogleChirp3,
    "google": GoogleChirp3,
    "fixture": lambda: FixtureStt({}),
}


class RealStt:
    """Implements `adapters.base.Stt`."""

    def __init__(self, registry: Mapping[str, SttFactory] | None = None) -> None:
        self._registry = dict(DEFAULT_REGISTRY if registry is None else registry)
        self._cache: dict[str, SttAdapter] = {}

    def _adapter(self, provider: str) -> SttAdapter:
        if provider not in self._cache:
            factory = self._registry.get(provider)
            if factory is None:
                raise ConfigError("unknown STT provider")
            self._cache[provider] = factory()
        return self._cache[provider]

    async def start(self, audio: AudioRef, params: SttParams) -> str:
        handle = await self._adapter(params.provider).start(audio, params)
        return json.dumps({"provider": params.provider, "handle": handle})

    async def poll(self, handle: str) -> Transcript | None:
        try:
            wrapped = json.loads(handle)
            provider, inner = wrapped["provider"], wrapped["handle"]
        except (ValueError, KeyError, TypeError):
            raise ConfigError("bad STT handle") from None
        return await self._adapter(provider).poll(inner)
