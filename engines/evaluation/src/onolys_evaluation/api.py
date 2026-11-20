"""Public function signatures (SP03 R1). Bodies land in later tasks; they raise until then."""

from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime
from typing import Any, Literal

from eaudit.models import AuditResponse
from onolys_core.engine import RunContext
from onolys_core.run_info import RunInfo, RunUsage
from onolys_core.run_info import code_version as _code_version
from onolys_core.transcript import Transcript
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
from onolys_evaluation.reasons import support_lines
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
    """R1: the whole `running` phase (paudit, reasons audit, tips, compare, assemble)."""
    raise NotImplementedError("SP03 later task")


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
        clin.update(rating.get("counts") or {})
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
            clinician_note=((rating or {}).get("count_notes") or {}).get(k),
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
