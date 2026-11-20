"""The assembled engine (PRD R2 step 9, R3, R4; Decisions 10-11).

`run(transcript, pack, params, client) -> PauditResult` wires prepare -> code pass + globals pass
(started together) -> rules/counts/summaries, repeats that `n_runs` times, and aggregates.
`PauditEngine` is the core `Engine` seam over it. Protocol-agnostic: everything protocol-specific
comes from the pack.

Failure (Decision 11): a run whose code or globals pass fails is excluded with a `run_failed`
warning; when every run fails `AllRunsFailed` is raised. A run keeps its original `run_index`.

Logging goes through `onolys_core.safe_log` with ids, counts and statuses only, never text.
"""

import asyncio
import hashlib
import inspect
import logging
import statistics
from pathlib import Path
from typing import Any

from onolys_core import EngineResult, InputError, OnolysError, PackRef, RunContext
from onolys_core.llm import LLMClient, LLMError, MetricsCollector
from onolys_core.llm.routes import Route, resolve_preset
from onolys_core.run_info import RunInfo, RunUsage, code_version, hash_files, route_facts
from onolys_core.safe_log import log_event, register_fields
from onolys_core.transcript import Transcript

from paudit import code_pass as code_mod
from paudit import globals_pass as globals_mod
from paudit.formula import label_for
from paudit.hooks import Hooks, load_hooks
from paudit.pack import Pack, load_pack
from paudit.prepare import Prepared, prepare
from paudit.result import (
    SCHEMA_VERSION,
    Aggregate,
    CodedSpan,
    PauditResult,
    ProtocolBlock,
    Reference,
    ResultWarning,
    RunResult,
    Stat,
    SummaryStat,
)
from paudit.score import score_run

register_fields({"run_index", "n_runs", "pack_id", "pack_version", "runs_ok"})

ROUTES = (code_mod.ROUTE, globals_mod.ROUTE)
_FAILURES = (code_mod.CodePassFailed, globals_mod.GlobalsPassFailed, LLMError)


class AllRunsFailed(OnolysError):
    """Every run failed, so there is nothing trustworthy to return (ADR 0012)."""

    code = "run_failed"


def _sha(*parts: str) -> str:
    h = hashlib.sha256()
    for p in parts:
        h.update(p.encode("utf-8"))
        h.update(b"\0")
    return h.hexdigest()[:16]


def prompt_hashes(pack: Pack) -> dict[str, str]:
    """Hash of every pack prompt file (keyed by file name) and of each engine-owned template
    (`engine:*`: output-format instructions and the definition/few-shot/batch renderers), so a
    template change shows even when the pack is unchanged. Computed per call (cheap)."""
    out = {p.name: hash_files([p]) for p in pack.prompt_paths}
    out["engine:code_output_format"] = _sha(code_mod._OUTPUT_FORMAT)
    code_fns = (code_mod._render_definitions, code_mod._render_fewshot, code_mod._render_batch)
    out["engine:code_templates"] = _sha(*(inspect.getsource(f) for f in code_fns))
    out["engine:globals_output_format"] = _sha(globals_mod._OUTPUT_FORMAT)
    glob_fns = (globals_mod._render_definitions, globals_mod._render_fewshot)
    out["engine:globals_templates"] = _sha(*(inspect.getsource(f) for f in glob_fns))
    return out


def _stat(values: list[float]) -> Stat:
    return Stat(mean=statistics.fmean(values), min=min(values), max=max(values), values=values)


def _summary_stat(values: list[float | None], ref: Reference | None) -> SummaryStat:
    known = [v for v in values if v is not None]
    mean = statistics.fmean(known) if known else None
    return SummaryStat(
        mean=mean,
        min=min(known) if known else None,
        max=max(known) if known else None,
        values=values,
        label=label_for(mean, ref.model_dump() if ref else None),
        reference=ref,
    )


def _vectors(runs: list[RunResult]) -> list[list[float]]:
    """One vector per run: counts, global scores, then summary values. A summary that is None in
    any run is left out for all runs (nothing to compare)."""
    first = runs[0]
    keys: list[tuple[str, str]] = [("c", k) for k in first.counts]
    keys += [("g", k) for k in first.globals]
    keys += [
        ("s", k)
        for k in first.summaries
        if all(r.summaries[k].value is not None for r in runs)
    ]

    def val(r: RunResult, kind: str, k: str) -> float:
        if kind == "c":
            return float(r.counts[k])
        if kind == "g":
            return float(r.globals[k].score)
        return float(r.summaries[k].value)  # type: ignore[arg-type]

    return [[val(r, kind, k) for kind, k in keys] for r in runs]


def representative_run(runs: list[RunResult]) -> int:
    """`run_index` of the run closest to the mean vector.

    Each run is a vector of its counts, its global scores and its summary values (summaries that
    are None in any run are left out). Each dimension is divided by its range across runs
    (max - min; dimensions where all runs agree are dropped), so counts, 1-5 scores and
    ratios weigh alike. The distance to the per-dimension mean is the Euclidean norm of the
    scaled differences. Smallest distance wins; ties go to the lowest `run_index`.
    """
    vecs = _vectors(runs)
    dims = list(zip(*vecs, strict=True))
    means = [statistics.fmean(d) for d in dims]
    ranges = [max(d) - min(d) for d in dims]

    def dist(v: list[float]) -> float:
        return sum(((x - m) / r) ** 2 for x, m, r in zip(v, means, ranges, strict=True) if r > 0)

    return min((dist(v), r.run_index) for v, r in zip(vecs, runs, strict=True))[1]


def aggregate(pack: Pack, runs: list[RunResult]) -> Aggregate:
    """mean/min/max/values over the runs (in run order) for counts, globals and summaries, plus
    `representative_run` (see `representative_run`). With one run the aggregate equals it."""
    if not runs:
        raise ValueError("aggregate needs at least one run")
    summaries = {}
    for sid in runs[0].summaries:
        ref = runs[0].summaries[sid].reference
        summaries[sid] = _summary_stat([r.summaries[sid].value for r in runs], ref)
    return Aggregate(
        counts={k: _stat([float(r.counts[k]) for r in runs]) for k in runs[0].counts},
        globals={k: _stat([float(r.globals[k].score) for r in runs]) for k in runs[0].globals},
        summaries=summaries,
        representative_run=representative_run(runs),
    )


async def _one_run(
    client: LLMClient,
    pack: Pack,
    prepared: Prepared,
    hooks: Hooks,
    params: dict[str, Any],
    language: str | None,
    run_index: int,
    metrics: MetricsCollector,
    warmed: asyncio.Event,
) -> RunResult:
    """Code pass and globals pass run together; the code pass sets `warmed` after its warm call."""
    kw = {"language": language, "run_index": run_index, "metrics": metrics}
    code_task = asyncio.ensure_future(
        code_mod.code_pass(client, pack, prepared, params, warmed=warmed, **kw)
    )
    globals_task = asyncio.ensure_future(
        globals_mod.globals_pass(client, pack, prepared, params, **kw)
    )
    done = await asyncio.gather(code_task, globals_task, return_exceptions=True)
    for d in done:
        if isinstance(d, BaseException):
            raise d
    code_res, glob_res = done
    scores = {k: g.score for k, g in glob_res.globals.items()}
    instances, counts, summaries, score_warns = score_run(pack, code_res.instances, scores, hooks)
    return RunResult(
        run_index=run_index,
        instances=instances,
        counts=counts,
        globals=glob_res.globals,
        summaries=summaries,
        warnings=[*code_res.warnings, *glob_res.warnings, *score_warns],
    )


def _usage(metrics: MetricsCollector) -> RunUsage:
    snap = metrics.snapshot()
    tiers = snap["by_tier"].values()
    return RunUsage(
        calls=snap["calls"],
        **{
            k: sum(t[k] for t in tiers)
            for k in ("input_tokens", "output_tokens", "cache_read_tokens", "cache_write_tokens")
        },
    )


def _route_view(
    client: Any, routes: dict[str, Route] | None, preset: str | None
) -> dict[str, Route]:
    found = routes if routes is not None else getattr(client, "routes", None)
    if not isinstance(found, dict):
        found = resolve_preset(preset)[0]
    return {n: found[n] for n in ROUTES if n in found}


def _language(params: dict[str, Any], transcript: Transcript) -> str:
    lang = params.get("language")
    if not lang or lang == "auto":
        lang = transcript.language
    return lang or "und"


async def run(
    transcript: Transcript,
    pack: Pack,
    params: dict[str, Any],
    client: LLMClient,
    *,
    metrics: MetricsCollector | None = None,
    request_id: str | None = None,
    routes: dict[str, Route] | None = None,
) -> PauditResult:
    """Rate `transcript` against `pack`. `params`: `speaker_map{subject}` (required),
    `change_goal`, `coded_span`, `language`, `n_runs` (default 1), `volleys_per_call`,
    `code_max_tokens`, `globals_max_tokens`, `preset` (provenance only: the client's routes decide
    the model). `routes` (default: `client.routes`, else the preset's) feed `run_info` only."""
    n_runs = int(params.get("n_runs") or 1)
    if n_runs < 1:
        raise InputError("n_runs must be at least 1")
    metrics = metrics if metrics is not None else MetricsCollector()
    hooks = load_hooks(pack)
    prepared = prepare(transcript, pack, params, hooks)
    language = _language(params, transcript)
    lang_arg = None if language == "und" else language
    log_event(
        "paudit.start",
        request_id=request_id,
        pack_id=pack.id,
        pack_version=pack.version,
        n_runs=n_runs,
        speakers=len({rt.turn.speaker for rt in prepared.turns}),
        language=language,
    )

    warnings: list[ResultWarning] = list(prepared.warnings)
    if not language.lower().startswith("en"):
        warnings.append(
            ResultWarning(
                code="language_not_validated",
                severity="info",
                detail=f"language {language} is not validated for this engine",
            )
        )

    events = [asyncio.Event() for _ in range(n_runs)]

    first_failure: list[BaseException] = []  # first run failure: the cause of AllRunsFailed

    async def guarded(i: int) -> RunResult | None:
        if i > 0:  # later runs start once the first run's warm call has returned
            await events[0].wait()
        try:
            res = await _one_run(
                client, pack, prepared, hooks, params, lang_arg, i, metrics, events[i]
            )
            log_event("paudit.run", request_id=request_id, run_index=i, status="ok")
            return res
        except _FAILURES as exc:
            first_failure.append(exc)
            warnings.append(
                ResultWarning(code="run_failed", detail=f"run {i} failed: {type(exc).__name__}")
            )
            log_event(
                "paudit.run",
                logging.WARNING,
                request_id=request_id,
                run_index=i,
                status="failed",
                exc_class=type(exc).__name__,
            )
            return None
        finally:
            events[i].set()

    outcomes = await asyncio.gather(*(guarded(i) for i in range(n_runs)))
    runs = [r for r in outcomes if r is not None]
    if not runs:
        log_event("paudit.done", logging.ERROR, request_id=request_id, status="failed", runs_ok=0)
        raise AllRunsFailed(f"all {n_runs} run(s) failed") from (
            first_failure[0] if first_failure else None
        )
    log_event(
        "paudit.done",
        request_id=request_id,
        status="ok",
        runs_ok=len(runs),
        calls=len(metrics.records),
    )

    routes_view = _route_view(client, routes, params.get("preset"))
    run_info = RunInfo(
        engine="paudit",
        code_version=code_version(),
        preset=params.get("preset"),
        routes={n: route_facts(r) for n, r in routes_view.items()},
        pack=pack.facts(),
        prompt_hashes=prompt_hashes(pack),
        n_runs=n_runs,
        usage=_usage(metrics),
    )
    span = params.get("coded_span")
    return PauditResult(
        schema_version=SCHEMA_VERSION,
        request_id=request_id,
        protocol=ProtocolBlock(
            id=pack.id, version=pack.version, pack_hash=pack.pack_hash, pack_format=pack.pack_format
        ),
        language=language,
        change_goal=params.get("change_goal"),
        coded_span=CodedSpan(**span) if span else None,
        subject_speaker=params["speaker_map"]["subject"],
        n_runs=n_runs,
        results=runs,
        aggregate=aggregate(pack, runs),
        warnings=warnings,
        run_info=run_info,
    )


class PauditEngine:
    """Core `Engine` seam: `pack` is a `PackRef` (its `path` is the pack directory). The client
    and metrics come from `ctx`; `ctx.llm.routes` (when present) feeds `run_info`."""

    name = "paudit"

    async def run(
        self,
        transcript: Transcript,
        pack: PackRef | None,
        params: dict,
        ctx: RunContext,
    ) -> EngineResult:
        if pack is None:
            raise InputError("paudit needs a pack")
        loaded = load_pack(Path(pack.path))
        result = await run(
            transcript,
            loaded,
            params,
            ctx.llm,
            metrics=ctx.metrics,
            request_id=ctx.request_id,
        )
        return EngineResult(result=result, run_info=result.run_info)
