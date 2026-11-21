"""EauditEngine: the core `Engine` seam over today's pipeline (core PRD R6, R10).

`POST /v1/audit` does not go through this. `params`: `assessment` (list of Section dicts,
required), optional `preset`, `n_runs` and `profile`. `profile` ({suppress_concerns,
context_note}) goes into the `AuditRequest` as its optional `profile` (contract 0.0.2).
"""

import time

from onolys_core.engine import EngineResult, PackRef, RunContext
from onolys_core.run_info import RunInfo, RunUsage, code_version, route_facts
from onolys_core.transcript import Transcript

from eaudit import run_info as eaudit_run_info
from eaudit.config import Settings
from eaudit.contract import SCHEMA_VERSION
from eaudit.models import AuditRequest
from eaudit.pipeline import Pipeline, RequestContext, make_pipeline, run_with_backstop


class EauditEngine:
    name = "eaudit"

    def __init__(self, settings: Settings | None = None, pipeline: Pipeline | None = None):
        self.settings = settings or Settings()
        self.pipeline = pipeline or make_pipeline(self.settings)

    async def run(
        self,
        transcript: Transcript,
        pack: PackRef | None,
        params: dict,
        ctx: RunContext,
    ) -> EngineResult:
        settings = self.settings
        req = AuditRequest.model_validate(
            {
                "schema_version": SCHEMA_VERSION,
                "request_id": ctx.request_id,
                "transcript": transcript.to_eaudit_turns(),
                "assessment": params["assessment"],
                **({"profile": params["profile"]} if params.get("profile") is not None else {}),
            }
        )
        rctx = RequestContext(
            settings=settings,
            llm=ctx.llm,
            metrics=ctx.metrics,
            request_id=ctx.request_id,
            deadline=ctx.deadline or time.monotonic() + settings.audit_deadline_s,
        )
        response = await run_with_backstop(self.pipeline, req, rctx, settings)
        return EngineResult(result=response, run_info=self._run_info(params, ctx))

    def _run_info(self, params: dict, ctx: RunContext) -> RunInfo:
        snap = ctx.metrics.snapshot()
        tiers = snap["by_tier"].values()
        usage = RunUsage(
            calls=snap["calls"],
            **{
                k: sum(t[k] for t in tiers)
                for k in (
                    "input_tokens",
                    "output_tokens",
                    "cache_read_tokens",
                    "cache_write_tokens",
                )
            },
        )
        routes = self.settings.llm_config().routes or {}
        return RunInfo(
            engine=self.name,
            code_version=code_version(),
            preset=params.get("preset"),
            routes={n: route_facts(r) for n, r in routes.items()},
            prompt_hashes=eaudit_run_info.prompt_hashes(),
            n_runs=params.get("n_runs", 1),
            usage=usage,
        )
