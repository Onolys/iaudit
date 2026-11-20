"""Real `Stt` adapter (SP09 R1, D5): a registry over the SP01 core STT adapters.

The provider is data: the worker passes the session's stored `stt.provider` in `SttParams`, and
this module looks the core adapter up by that key. There is no `if provider == ...` in worker
code. A new STT provider is one core adapter plus one `DEFAULT_REGISTRY` line (and its
`stt_providers.yaml` entry).

`poll(handle)` carries no provider, so `start` wraps the core handle as
`{"provider", "handle"}` JSON; `stt_operation` stores that string and `poll` routes on it.
The `Transcript` (incl. `stt_run`) from the core adapter is returned unchanged.

`RealEvaluation` (SP09 R2, D5) is the single call into `onolys_evaluation.run_evaluation`; it names
no model or provider: routes come from the run's preset (`resolve_preset`, unknown preset ->
core `InputError`). The pack directory resolves through `PAUDIT_PROTOCOLS_DIR` (else the repo's
`protocols/`).

An unknown provider raises core `ConfigError` (an `OnolysError`): `error_map.to_public` maps it
to `internal_error`, not retryable, and the worker logs the class, never the message.
"""

import json
import time
from collections.abc import Callable, Mapping
from typing import Any

from onolys_core.engine import PackRef, RunContext
from onolys_core.errors import ConfigError
from onolys_core.llm import LiteLLMClient, LLMConfig, MetricsCollector
from onolys_core.llm.routes import resolve_preset
from onolys_core.stt import AudioRef, SttAdapter, SttParams
from onolys_core.stt.fixture import FixtureStt
from onolys_core.stt.google_chirp import GoogleChirp3
from onolys_core.transcript import Transcript

from onolys_api.adapters.base import EvaluationOutput, ProgressCb

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


PACK_REF = "miti@4.2.1"
RUN_DEADLINE_S = 8 * 60  # the whole evaluation; a shorter ctx.deadline (task budget) wins
_ENGINE_PARAMS = ("change_goal", "coded_span", "language", "n_runs", "preset", "code_version")


def _llm_from_routes(routes: dict) -> Any:
    return LiteLLMClient(LLMConfig(routes=routes))


class RealEvaluation:
    """Implements `adapters.base.Evaluation`: one `run_evaluation` call, nothing else."""

    def __init__(
        self,
        run_evaluation: Callable[..., Any] | None = None,
        pack_loader: Callable[[str], Any] | None = None,
        llm_factory: Callable[[dict], Any] = _llm_from_routes,
    ) -> None:
        self._run_evaluation = run_evaluation
        self._pack_loader = pack_loader
        self._llm_factory = llm_factory

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
        run_evaluation, load_pack = self._run_evaluation, self._pack_loader
        if run_evaluation is None:
            from onolys_evaluation.api import run_evaluation
        if load_pack is None:
            from paudit.pack import load_pack
        routes, _ = resolve_preset(params.get("preset"))  # unknown preset: InputError
        deadline = time.monotonic() + RUN_DEADLINE_S
        if ctx.deadline is not None:
            deadline = min(deadline, ctx.deadline)
        rctx = RunContext(
            llm=self._llm_factory(routes),
            metrics=MetricsCollector(),
            request_id=ctx.request_id,
            deadline=deadline,
        )
        engine_params = {k: params.get(k) for k in _ENGINE_PARAMS}
        out = await run_evaluation(
            rctx, load_pack(PACK_REF), transcript, speaker_map, engine_params, rating, None,
            progress_cb,
        )  # fmt: skip
        return EvaluationOutput(
            report=json.loads(out.report.model_dump_json()),
            artifacts=json.loads(out.artifacts.model_dump_json()),
        )
