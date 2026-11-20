"""R4/D6/D10: deterministic compare and explanation templates. No model call, no protocol words:
thresholds come from `pack.yaml > compare`, summary formulas from `pack.yaml > summaries`
(through paudit's public `formula.evaluate`), headline from `report.yaml`.

Sign convention (PRD R4): `signed = onolys - clinician`."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from paudit.formula import evaluate, label_for
from paudit.pack import Pack
from paudit.result import PauditResult, SummaryStat

from onolys_evaluation.report import (
    Diff,
    Explanation,
    Instance,
    Line,
    SummaryEntry,
    SummaryReference,
    SummaryValue,
    Warning,
)
from onolys_evaluation.tone import ReportConfig, ToneRules

# Engine templates (neutral wording; linted against the pack's banned list by a unit test).
HEADLINE_AGREE = "Onolys agrees"
HEADLINE_NEUTRAL = "Onolys's reading"
SCORED = "Onolys scored {o}; you scored {c}."
COUNTED = "Onolys counted {o}; you counted {c}."
SCORED_ONLY = "Onolys scored {o}."
COUNTED_ONLY = "Onolys counted {o}."
NO_VALUE = "Onolys has no value for this item; you recorded {c}."
NOTE_BOTH = "Both values use the same formula. Reference levels, not pass marks."
NOTE_ONOLYS = "Onolys values only. Reference levels, not pass marks."


def template_strings() -> list[str]:
    return [HEADLINE_AGREE, HEADLINE_NEUTRAL, SCORED, COUNTED, SCORED_ONLY, COUNTED_ONLY,
            NO_VALUE, NOTE_BOTH, NOTE_ONOLYS]


@dataclass(frozen=True)
class CompareRule:
    kind: str  # "score_diff" | "count_diff"
    differs_at: float = 1
    within: float = 1
    flag_abs: float = 2
    flag_rel: float = 0.25


def compare_rules(pack: Pack) -> dict[str, CompareRule]:
    """Per-item rules read from `pack.yaml > compare`."""
    out = {}
    for item_id, spec in (pack.data.get("compare") or {}).items():
        kw = {k: v for k, v in spec.items() if k != "kind"}
        out[item_id] = CompareRule(spec["kind"], **kw)
    return out


def compare_item(rule: CompareRule, clinician: float | None, onolys: float | None) -> Diff:
    """Diff for one item. Onolys missing -> `no_onolys_value`; clinician missing -> `not_rated`.

    global: `differs = abs >= differs_at`, `within_one = abs <= within`.
    count: `agree` if signed == 0; `flagged` if abs >= flag_abs or abs / max(c, o) >= flag_rel;
    otherwise `differs`."""
    if onolys is None:
        return Diff(signed=None, abs=None, direction=None, status="no_onolys_value")
    if clinician is None:
        return Diff(signed=None, abs=None, direction=None, status="not_rated")
    signed = onolys - clinician
    a = abs(signed)
    direction = "same" if signed == 0 else "onolys_higher" if signed > 0 else "onolys_lower"
    if rule.kind == "score_diff":
        status = "differs" if a >= rule.differs_at else "agree"
        return Diff(signed=signed, abs=a, direction=direction, status=status,
                    within_one=a <= rule.within)
    if signed == 0:
        status = "agree"
    elif a >= rule.flag_abs or a / max(abs(clinician), abs(onolys)) >= rule.flag_rel:
        status = "flagged"
    else:
        status = "differs"
    return Diff(signed=signed, abs=a, direction=direction, status=status)


def compare_summaries(pack: Pack, clinician_values: Mapping[str, float | None] | None,
                      onolys: Mapping[str, SummaryStat]) -> list[SummaryEntry]:
    """Summary rows. The clinician value uses the pack formula over their own inputs; the whole
    `clinician` is null with no rating, a missing input, or a divide by zero."""
    out = []
    for s in pack.data.get("summaries", []):
        ref = s.get("reference")
        cv = evaluate(s["expr"], clinician_values) if clinician_values is not None else None
        o = onolys[s["id"]]
        out.append(SummaryEntry(
            id=s["id"], label=s["label"],
            clinician=None if cv is None else SummaryValue(value=cv, label=label_for(cv, ref)),
            onolys=SummaryValue(value=o.mean, label=o.label),
            reference=SummaryReference(fair=ref["fair"], good=ref["good"]) if ref else None,
            note=NOTE_BOTH if clinician_values is not None else NOTE_ONOLYS))
    return out


def representative_instances(result: PauditResult, code: str) -> list[Instance]:
    """Counted instances of `code` from the representative run (all of them; the UI shows the
    first `max_instances_shown`)."""
    idx = result.aggregate.representative_run
    run = next(r for r in result.results if r.run_index == idx)
    return [Instance(id=i.id, turn_id=i.turn_id, start=i.start, end=i.end, quote=i.quote,
                     rationale=i.rationale)
            for i in run.instances if i.counted and i.code == code]


def _num(v: float) -> str:
    return str(int(v)) if float(v).is_integer() else f"{v:.2f}".rstrip("0").rstrip(".")


def _line(x: Line) -> Line:
    return Line(turn_id=x.turn_id, start=x.start, end=x.end, quote=x.quote)


def explain(*, item_id: str, kind: str, label: str, diff: Diff, onolys_value: float | None,
            clinician_value: float | None, reason: str | None, onolys_lines: Sequence[Line],
            support_lines: Sequence[Line], rules: ToneRules, cfg: ReportConfig
            ) -> tuple[Explanation, list[Warning]]:
    """Template explanation. `support_lines` are the supported reasons-audit evidence lines for
    the item (mapped by the caller). A reason that fails the tone lint is withheld and
    `reason_withheld_tone` is returned; evidence lines are kept."""
    warnings: list[Warning] = []
    counted = kind == "count"
    if diff.status == "no_onolys_value":
        body = [NO_VALUE.format(c=_num(clinician_value))] if clinician_value is not None else []
        headline = HEADLINE_NEUTRAL
    elif clinician_value is None:
        body = [(COUNTED_ONLY if counted else SCORED_ONLY).format(o=_num(onolys_value))]
        headline = HEADLINE_NEUTRAL
    else:
        body = [(COUNTED if counted else SCORED).format(o=_num(onolys_value),
                                                         c=_num(clinician_value))]
        headline = HEADLINE_AGREE if diff.status == "agree" else cfg.headline
    if reason:
        if rules.lint(reason):
            warnings.append(Warning(code="reason_withheld_tone", item_id=item_id))
        else:
            body.append(reason)
    return Explanation(headline=headline, body=body,
                       onolys_lines=[_line(x) for x in onolys_lines],
                       clinician_support_lines=[_line(x) for x in support_lines]), warnings


__all__ = ["CompareRule", "compare_item", "compare_rules", "compare_summaries", "explain",
           "representative_instances", "template_strings"]
