"""Public API (SP03 R1): `run_evaluation` orchestration and the pure `build_report` assembly."""

import asyncio
import time
from collections.abc import Awaitable, Callable, Mapping, Sequence
from datetime import UTC, datetime
from typing import Any, Literal

from eaudit.api.errors import DeadlineExceeded
from eaudit.config import Settings as EauditSettings
from eaudit.engine import EauditEngine
from eaudit.models import AuditRequest, AuditResponse
from eaudit.models import Status as EauditStatus
from eaudit.pipeline import RequestContext, run_with_backstop
from onolys_core.engine import RunContext
from onolys_core.llm import MetricsCollector
from onolys_core.run_info import RunInfo, RunUsage, route_facts
from onolys_core.run_info import code_version as _code_version
from onolys_core.safe_log import log_event, register_fields
from onolys_core.transcript import Transcript
from paudit.engine import run as paudit_run
from paudit.pack import Pack
from paudit.result import PauditResult
from pydantic import BaseModel

from onolys_evaluation.compare import (
    METHOD_LIMIT,
    compare_item,
    compare_rules,
    compare_summaries,
    explain,
    representative_instances,
)
from onolys_evaluation.rating import is_no_rating, validate_rating  # noqa: F401
from onolys_evaluation.reasons import build_reasons_request, map_reasons_response, support_lines
from onolys_evaluation.report import (
    SCHEMA_VERSION,
    Aggregates,
    AuditItem,
    BehaviourEntry,
    ClinicianGlobal,
    Diff,
    GlobalEntry,
    Header,
    LayoutEntry,
    Line,
    Method,
    OnolysGlobal,
    Protocol,
    RatingCoverage,
    Report,
    ReportRunInfo,
    RunStats,
    ScorecardRow,
    Tip,
    Warning,
)
from onolys_evaluation.tone import ReportConfig, load_report_config, tone_rules

Stage = Literal["paudit", "eaudit", "tips", "compare", "assemble"]
StageStatus = Literal["started", "done", "failed"]
ProgressCb = Callable[[Stage, StageStatus], None]


class TipsArtifact(BaseModel):
    """Validated tips plus the raw model proposals (for audit; never shown to users)."""

    valid: list[Tip]
    proposals: list[dict[str, Any]]


class Artifacts(BaseModel):
    paudit: PauditResult
    eaudit: AuditResponse | None = None
    tips: TipsArtifact | None = None


class EvaluationOutput(BaseModel):
    """The report plus run artifacts. `run_info` is `report.run_info`."""

    report: Report
    artifacts: Artifacts


register_fields({"stage", "stage_status"})


def _emit(cb: ProgressCb | None, stage: Stage, status: StageStatus,
          request_id: str | None) -> None:
    """Call the progress callback; an error in it is logged (class name only) and ignored."""
    if cb is None:
        return
    try:
        cb(stage, status)
    except Exception as exc:  # noqa: BLE001 - a callback must never break the run
        log_event("evaluation.progress_cb_error", request_id=request_id, stage=stage,
                  stage_status=status, exc_class=type(exc).__name__)


async def _run_paudit(transcript: Transcript, pack: Pack, params: dict[str, Any], ctx: RunContext,
                      metrics: MetricsCollector) -> PauditResult:
    """Seam over `paudit.engine.run` (tests replace it)."""
    return await paudit_run(transcript, pack, params, ctx.llm, metrics=metrics,
                            request_id=ctx.request_id)


async def _run_eaudit(request: AuditRequest, ctx: RunContext,
                      metrics: MetricsCollector) -> tuple[AuditResponse, RunInfo]:
    """Seam over eaudit's pipeline (same engine the core `EauditEngine` wraps), with the request
    built by `build_reasons_request` so roles and the audit profile are set. Raises
    `DeadlineExceeded` on the hard deadline."""
    settings = EauditSettings()
    engine = EauditEngine(settings)
    rctx = RequestContext(
        settings=settings, llm=ctx.llm, metrics=metrics, request_id=ctx.request_id,
        deadline=ctx.deadline or time.monotonic() + settings.audit_deadline_s)
    response = await run_with_backstop(engine.pipeline, request, rctx, settings)
    inner = RunContext(llm=ctx.llm, metrics=metrics, request_id=ctx.request_id)
    return response, engine._run_info({}, inner)


def _usage(metrics: MetricsCollector) -> RunUsage:
    snap = metrics.snapshot()
    tiers = snap["by_tier"].values()
    return RunUsage(calls=snap["calls"], **{
        k: sum(t[k] for t in tiers)
        for k in ("input_tokens", "output_tokens", "cache_read_tokens", "cache_write_tokens")})


async def _stage[T](cb: ProgressCb | None, stage: Stage, rid: str | None,
                    work: Awaitable[T]) -> T:
    """`started`, then `done`, or `failed` (cancellation counts as failed) if `work` raises."""
    _emit(cb, stage, "started", rid)
    try:
        out = await work
    except BaseException:
        _emit(cb, stage, "failed", rid)
        raise
    _emit(cb, stage, "done", rid)
    return out


async def _value[T](v: T) -> T:
    return v


async def run_evaluation(
    ctx: RunContext,
    pack: Pack,
    transcript: Transcript,
    speaker_map: dict[str, str],
    params: dict[str, Any],
    rating: dict[str, Any] | None,
    paudit_result: PauditResult | None,
    progress_cb: ProgressCb | None = None,
) -> EvaluationOutput:
    """R1: the whole `running` phase (paudit, reasons audit, tips, compare, assemble).

    The reasons audit starts at t0 next to paudit (it runs whenever there is a rating with text to
    audit, also when `paudit_result` is supplied; a supplied result only replaces the paudit
    stage). Tips start once paudit is done and run next to the reasons audit. A paudit failure
    raises (the reasons audit still in flight is cancelled and no report is built); a reasons-audit
    failure or timeout and a tips failure degrade to warnings. Log lines carry ids and statuses."""
    from onolys_evaluation.hashes import evaluation_prompt_hashes
    from onolys_evaluation.tips import ROUTE as TIPS_ROUTE
    from onolys_evaluation.tips import generate_tips

    rid = ctx.request_id
    card = None if is_no_rating(rating) else rating
    built = build_reasons_request(pack, transcript, speaker_map, card, request_id=rid)
    paudit_metrics, eaudit_metrics = MetricsCollector(), MetricsCollector()
    warnings: list[Warning] = []
    state: dict[str, Any] = {"response": None, "info": None, "partial": False, "failed": False,
                            "ended": built is None}
    log_event("evaluation.start", request_id=rid, step="start")

    async def reasons() -> list[AuditItem] | None:
        assert built is not None
        try:
            response, info = await _run_eaudit(built.request, ctx, eaudit_metrics)
        except (DeadlineExceeded, TimeoutError):
            state["partial"] = True
            log_event("evaluation.reasons", request_id=rid, status="timeout")
            raise
        except Exception as exc:
            state["failed"] = True
            log_event("evaluation.reasons", request_id=rid, status="error",
                      exc_class=type(exc).__name__)
            raise
        state["response"], state["info"] = response, info
        state["partial"] = response.status == EauditStatus.partial
        return map_reasons_response(response, built, transcript)

    _emit(progress_cb, "eaudit", "started", rid)  # eager: the stage starts at t0
    if built is None:  # not applicable (no rating / nothing to audit): done at once
        _emit(progress_cb, "eaudit", "done", rid)

    async def reasons_stage() -> list[AuditItem] | None:
        try:
            out = await reasons()
        except Exception:  # noqa: BLE001 - kept in `state`, becomes a warning; report ships
            _emit(progress_cb, "eaudit", "failed", rid)
            state["ended"] = True
            return None
        _emit(progress_cb, "eaudit", "done", rid)
        state["ended"] = True
        return out

    async def paudit_stage() -> PauditResult:
        if paudit_result is not None:  # supplied: reuse it
            return await _stage(progress_cb, "paudit", rid, _value(paudit_result))
        p = {**params, "speaker_map": speaker_map}
        return await _stage(progress_cb, "paudit",
                            rid, _run_paudit(transcript, pack, p, ctx, paudit_metrics))

    async def tips_stage(result: PauditResult) -> TipsArtifact:
        _emit(progress_cb, "tips", "started", rid)
        art, tw = await generate_tips(ctx.llm, pack, transcript, speaker_map, result,
                                      metrics=ctx.metrics)
        warnings.extend(tw)
        failed = any(w.code == "tips_failed" for w in tw)
        _emit(progress_cb, "tips", "failed" if failed else "done", rid)
        return art

    reasons_task: asyncio.Future[list[AuditItem] | None] = (
        asyncio.create_task(reasons_stage()) if built is not None
        else asyncio.get_running_loop().create_future())
    if built is None:
        reasons_task.set_result(None)
    tips_task: asyncio.Task[TipsArtifact] | None = None
    try:
        result = await paudit_stage()
        tips_task = asyncio.create_task(tips_stage(result))
        items = await reasons_task
        tips = await tips_task
    except BaseException:  # paudit failed (or the run was cancelled): wind down, build nothing
        pending = [t for t in (reasons_task, tips_task) if t is not None]
        for t in pending:
            t.cancel()
        await asyncio.gather(*pending, return_exceptions=True)
        if not state["ended"]:  # cancelled while in flight: still one terminal status
            _emit(progress_cb, "eaudit", "failed", rid)
        raise

    evaluation_usage = _usage(ctx.metrics)  # the evaluation run's own calls (tips)
    ctx_records = getattr(ctx.metrics, "records", None)
    if isinstance(ctx_records, list):  # one call log for the whole run
        ctx_records += paudit_metrics.records + eaudit_metrics.records
    route = getattr(ctx.llm, "routes", {}).get(TIPS_ROUTE) if hasattr(ctx.llm, "routes") else None
    kw: dict[str, Any] = {
        "pack": pack, "transcript": transcript, "speaker_map": speaker_map, "params": params,
        "rating": card, "paudit_result": result, "reasons_items": items,
        "reasons_failed": state["failed"], "reasons_partial": state["partial"], "tips": tips,
        "warnings": warnings, "prompt_hashes": evaluation_prompt_hashes(pack),
        "evaluation_routes": {TIPS_ROUTE: route_facts(route)} if route is not None else None,
        "evaluation_usage": evaluation_usage, "eaudit_run_info": state["info"],
        "request_id": rid}
    _emit(progress_cb, "compare", "started", rid)
    try:
        report = build_report(**kw)
    except BaseException:
        _emit(progress_cb, "compare", "failed", rid)
        raise
    _emit(progress_cb, "compare", "done", rid)
    _emit(progress_cb, "assemble", "started", rid)
    out = EvaluationOutput(report=report, artifacts=Artifacts(
        paudit=result, eaudit=state["response"], tips=tips))
    _emit(progress_cb, "assemble", "done", rid)
    log_event("evaluation.done", request_id=rid, status="ok")
    return out


def _stats(s: Any) -> RunStats:
    return RunStats(mean=s.mean, min=s.min, max=s.max, values=list(s.values))


def build_report(
    *,
    pack: Pack,
    transcript: Transcript,
    speaker_map: Mapping[str, str],
    params: Mapping[str, Any],
    rating: Mapping[str, Any] | None,
    paudit_result: PauditResult,
    reasons_items: Sequence[AuditItem] | None = None,
    reasons_failed: bool = False,
    reasons_partial: bool = False,
    tips: TipsArtifact | None = None,
    warnings: Sequence[Warning] = (),
    models: Mapping[str, str] | None = None,
    prompt_hashes: Mapping[str, str] | None = None,
    evaluation_routes: Mapping[str, Any] | None = None,
    evaluation_usage: RunUsage | None = None,
    eaudit_run_info: RunInfo | None = None,
    cfg: ReportConfig | None = None,
    request_id: str | None = None,
    created_at: str | None = None,
) -> Report:
    """R1/R7: pure assembly from already-computed parts; no model call, nothing truncated.

    `rating` None = no clinician rating: Onolys values only, `reasons_audit.status: skipped`,
    null aggregates (tips and method kept). `reasons_items` are mapped reasons-audit items
    (templated explanations only; no suggested revisions exist in `AuditItem`).
    `reasons_failed` -> status `failed`; `reasons_partial` -> status `partial`; both add their
    warning. `warnings` are extra warnings from earlier stages (tips, reasons, ...); paudit's own
    warnings are passed through. `models` maps route name -> litellm id (merged over paudit's
    routes). `prompt_hashes` are the evaluation run's (see `hashes.evaluation_prompt_hashes`)."""
    cfg = cfg or load_report_config(pack.root / "report.yaml")
    rules, tone = compare_rules(pack), tone_rules(pack)
    has_rating = rating is not None
    rep_idx = paudit_result.aggregate.representative_run
    rep = next(r for r in paudit_result.results if r.run_index == rep_idx)
    agg = paudit_result.aggregate
    labels = {i["id"]: i["label"] for i in pack.items}
    global_ids = [i["id"] for i in pack.items if i["kind"] == "global"]
    count_ids = [i["id"] for i in pack.items if i["kind"] == "count"]

    clin: dict[str, Any] = {}
    if rating:
        clin = {g: (v or {}).get("score") for g, v in (rating.get("globals") or {}).items()}
        clin.update({k: (v or {}).get("count") for k, v in (rating.get("counts") or {}).items()})
    rated = sum(1 for k in global_ids + count_ids if clin.get(k) is not None)

    out_warnings: list[Warning] = [Warning(code=w.code, item_id=w.item_id)
                                   for w in paudit_result.warnings]
    items = list(reasons_items or [])
    scorecard: list[ScorecardRow] = []
    globals_: list[GlobalEntry] = []
    behaviours: list[BehaviourEntry] = []
    diffs: dict[str, Diff] = {}

    for g in global_ids:
        o, c = agg.globals[g], clin.get(g)
        gl = rep.globals[g]
        d = diffs[g] = compare_item(rules[g], c, o.mean)
        scorecard.append(ScorecardRow(
            item_id=g, kind="global", label=labels[g], clinician={"value": c},
            onolys={"value": gl.score, **_stats(o).model_dump()}, diff=d))
        crit = ((rating or {}).get("globals") or {}).get(g) or {}
        clinician = ClinicianGlobal(value=c, reason=crit.get("reason"),
                                    example=crit.get("example"))
        evidence = [Line(turn_id=e.turn_id, start=e.start, end=e.end, quote=e.quote)
                    for e in gl.evidence]
        expl, w = explain(
            item_id=g, kind="global", label=labels[g], diff=d, onolys_value=o.mean,
            clinician_value=c, reason=gl.reason, onolys_lines=evidence,
            support_lines=support_lines(items, g), rules=tone, cfg=cfg)
        out_warnings += w
        globals_.append(GlobalEntry(
            item_id=g, onolys=OnolysGlobal(score=gl.score, source=gl.source, reason=gl.reason,
                                           evidence=evidence),
            clinician=clinician, diff=d, explanation=expl))

    for k in count_ids:
        o, c = agg.counts[k], clin.get(k)
        d = diffs[k] = compare_item(rules[k], c, o.mean)
        scorecard.append(ScorecardRow(
            item_id=k, kind="count", label=labels[k], clinician={"value": c},
            onolys={"value": o.mean, **_stats(o).model_dump()}, diff=d))
        inst = representative_instances(paudit_result, k)
        expl, w = explain(
            item_id=k, kind="count", label=labels[k], diff=d, onolys_value=o.mean,
            clinician_value=c, reason=None, onolys_lines=inst,
            support_lines=support_lines(items, k), rules=tone, cfg=cfg)
        out_warnings += w
        behaviours.append(BehaviourEntry(
            item_id=k, clinician_count=c,
            clinician_note=(((rating or {}).get("counts") or {}).get(k) or {}).get("note"),
            onolys_count=_stats(o), instances=inst, instances_total=len(inst), diff=d,
            explanation=expl))

    summaries = compare_summaries(
        pack, {k: clin.get(k) for k in global_ids + count_ids} if has_rating else None,
        agg.summaries)

    if not has_rating:
        status = "skipped"
    elif reasons_failed:
        status = "failed"
        out_warnings.append(Warning(code="reasons_audit_failed"))
    elif reasons_partial:
        status = "partial"
        out_warnings.append(Warning(code="reasons_audit_partial"))
    else:
        status = "ran" if items else "skipped"

    compared = [diffs[g].abs for g in global_ids if diffs[g].abs is not None]
    count_rated = [k for k in count_ids if clin.get(k) is not None]
    aggregates = Aggregates(
        globals_compared=len(compared),
        avg_abs_global_difference=sum(compared) / len(compared) if compared else None,
        within_one_share=(sum(1 for g in global_ids if diffs[g].within_one) / len(compared)
                          if compared else None),
        counts_flagged=(sum(1 for k in count_rated if diffs[k].status == "flagged")
                        if count_rated else None))

    seen: set[tuple[str, str | None]] = set()
    final_warnings: list[Warning] = []
    for w in [*out_warnings, *warnings]:
        if (w.code, w.item_id) not in seen:
            seen.add((w.code, w.item_id))
            final_warnings.append(w)

    stt = transcript.stt_run
    pf = paudit_result.run_info.routes
    routes = {n: r.litellm_id for n, r in pf.items()} | dict(models or {})
    eval_info = RunInfo(
        engine="evaluation", code_version=params.get("code_version") or _code_version(),
        preset=params.get("preset"), routes=dict(evaluation_routes or {}), stt=stt,
        pack=pack.facts(), prompt_hashes=dict(prompt_hashes or {}), n_runs=paudit_result.n_runs,
        usage=evaluation_usage or RunUsage())
    span = paudit_result.coded_span
    return Report(
        schema_version=SCHEMA_VERSION,
        request_id=request_id,
        created_at=created_at or datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        header=Header(
            change_goal=paudit_result.change_goal,
            protocol=Protocol(id=pack.id, version=pack.version, pack_hash=pack.pack_hash,
                              label=f"{pack.id.upper()} {pack.version}"),
            language=paudit_result.language,
            coded_span=span.model_dump() if span else None,
            subject_speaker=paudit_result.subject_speaker or speaker_map["subject"],
            n_runs=paudit_result.n_runs, models=routes, stt=stt, preset=params.get("preset"),
            code_version=eval_info.code_version, params=dict(params),
            has_clinician_rating=has_rating,
            rating_coverage=RatingCoverage(rated=rated, total=len(global_ids) + len(count_ids))),
        layout=[LayoutEntry(**e) for e in cfg.layout()],
        scorecard=scorecard, globals=globals_, behaviours=behaviours, summaries=summaries,
        reasons_audit={"status": status, "items": items if has_rating else []},
        tips=list(tips.valid) if tips else [],
        method=Method(statement=cfg.method.statement, limits=[*cfg.method.limits, METHOD_LIMIT],
                      not_official_miti_coding=True, citation=cfg.method.citation),
        aggregates=aggregates, warnings=final_warnings,
        run_info=ReportRunInfo(evaluation=eval_info, paudit=paudit_result.run_info,
                               eaudit=eaudit_run_info if has_rating else None))
