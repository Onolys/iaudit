"""Generates the three report fixtures under protocols/miti-4.2.1/fixtures/evaluation/ from the
synthetic transcript and the stub-generated PauditResult in the same folder. All text is
SYNTHETIC; every quote is cut from the fixture transcript by substring, so offsets are exact
(code points).

    uv run --package onolys-evaluation python engines/evaluation/tests/_make_fixtures.py --write

A test keeps the committed JSON in sync with this module. Fixture-only comparison arithmetic
lives here; the real compare step lands in a later task."""

import json
import sys
from pathlib import Path
from typing import Any

import yaml
from onolys_core.run_info import RunInfo
from onolys_core.stt import SttRun
from paudit.pack import load_pack
from paudit.result import PauditResult

from onolys_evaluation.compare import compare_item, compare_rules, compare_summaries, explain
from onolys_evaluation.report import Diff, Line
from onolys_evaluation.tone import load_report_config, tone_rules

REPO = Path(__file__).resolve().parents[3]
PACK = REPO / "protocols" / "miti-4.2.1"
OUT = PACK / "fixtures" / "evaluation"
_PACK = load_pack(PACK)
RULES = compare_rules(_PACK)
TONE = tone_rules(_PACK)
CFG = load_report_config(PACK / "report.yaml")
CREATED_AT = "2026-11-20T00:00:00Z"

GLOBALS = ["cct", "sst", "partnership", "empathy"]
COUNTS = ["gi", "persuade", "persuade_permission", "question", "sr", "cr", "affirm",
          "seek_collab", "emphasize_autonomy", "confront"]

FULL_RATING: dict[str, Any] = {
    "globals": {
        "cct": {"score": 3, "reason": "The clinician asked what made walking important and the client then named their blood pressure and their kids.",
                "example": {"at_s": 165, "text": "What makes walking more important to you right now?"}},
        "sst": {"score": 4, "reason": "The clinician moved on from the client's tiredness quickly and returned to the plan."},
        "partnership": {"score": 5, "reason": "The clinician asked permission before offering ideas."},
        "empathy": {"score": 3, "reason": "Several reflections, but few went beyond what the client had said."},
    },
    "counts": {"gi": 2, "persuade": 0, "persuade_permission": 1, "question": 6, "sr": 4, "cr": 3,
               "affirm": 2, "seek_collab": 2, "emphasize_autonomy": 1, "confront": 0},
    "count_notes": {"sr": "Counted the short repeats of the client's words."},
    "notes": "A collaborative session. The client left with a plan for three lunch walks.",
}
PARTIAL_RATING: dict[str, Any] = {
    "globals": {
        "cct": {"score": 4, "reason": "The clinician asked what made walking important, then kept returning to the client's reasons."},
        "partnership": {"score": 5},
    },
    "counts": {"question": 6, "cr": 3},
    "count_notes": {},
    "notes": None,
}

TIPS = [
    ("question", "t11", "How confident are you, from one to ten, that you can make three lunch walks happen?",
     "Several prompts sit in one turn, which can make it hard for the client to know which to answer.",
     "How confident are you that you can make three lunch walks happen?",
     "One clear question leaves room for the client's own answer."),
    ("sr", "t8", "You're tired in the evenings.",
     "A short repeat of what the client said earlier adds little new.",
     "You're tired by evening, and still you found the energy for those Saturday walks.",
     "A reflection that adds meaning keeps the client exploring."),
    ("question", "t13", "Why a six and not a three?",
     "A why question can sound like a challenge to the client's answer.",
     "What gives you a six and keeps it from being lower?",
     "Open phrasing invites the client's own reasons for change."),
]

CLAIMS = {  # reason text -> (claim span, verdict, explanation, evidence [(role, turn, substring)])
    "cct": ("The clinician asked what made walking important", "supported",
            "The clinician asked this in turn t4.", [("supporting", "t4", "What makes walking more important to you right now?")]),
    "sst": ("The clinician moved on from the client's tiredness quickly", "partially_supported",
            "The clinician acknowledged tiredness once, then asked about timing.",
            [("supporting", "t9", "Where would a walk fit best in your week?"),
             ("qualifying", "t8", "You're tired in the evenings.")]),
    "partnership": ("The clinician asked permission before offering ideas", "supported",
                    "The clinician asked before sharing ideas.",
                    [("supporting", "t15", "Would it be helpful if I shared some ideas")]),
    "notes": ("The client left with a plan for three lunch walks", "supported",
              "The client and clinician summarised the plan at the end.",
              [("supporting", "t19", "three lunch walks, with indoor laps when it rains")]),
}


def _load(name: str) -> Any:
    return json.loads((OUT / name).read_text(encoding="utf-8"))


def _line(turns: dict[str, str], turn_id: str, sub: str) -> dict[str, Any]:
    start = turns[turn_id].index(sub)
    return {"turn_id": turn_id, "start": start, "end": start + len(sub), "quote": sub}


def _diff(kind: str, clin: float | None, onolys: float | None, item_id: str) -> dict[str, Any]:
    d = compare_item(RULES[item_id], clin, onolys)
    return d.model_dump(exclude_none=True) | {
        k: None for k in ("signed", "abs", "direction") if getattr(d, k) is None}


def _expl(item_id, kind, label, d, o, c, reason, lines, support) -> dict[str, Any]:
    e, _ = explain(item_id=item_id, kind=kind, label=label, diff=Diff(**d), onolys_value=o,
                   clinician_value=c, reason=reason, onolys_lines=[Line(**{k: x[k] for k in ("turn_id", "start", "end", "quote")}) for x in lines],
                   support_lines=[Line(**x) for x in support], rules=TONE, cfg=CFG)
    return e.model_dump(mode="json")


def _stats(s: dict[str, Any]) -> dict[str, Any]:
    return {"mean": s["mean"], "min": s["min"], "max": s["max"], "values": s["values"]}


def build(variant: str) -> dict[str, Any]:
    transcript = _load("transcript.json")
    paudit = _load("paudit_result.json")
    speaker_map = _load("speaker_map.json")
    pack = yaml.safe_load((PACK / "pack.yaml").read_text(encoding="utf-8"))
    report_yaml = yaml.safe_load((PACK / "report.yaml").read_text(encoding="utf-8"))
    labels = {i["id"]: i["label"] for i in pack["items"]}
    turns = {t["id"]: t["text"] for t in transcript["turns"]}
    rating = {"full": FULL_RATING, "partial": PARTIAL_RATING, "no_rating": None}[variant]
    rep = paudit["results"][0]
    agg = paudit["aggregate"]

    clin: dict[str, Any] = {}
    if rating:
        for g, v in rating["globals"].items():
            clin[g] = v.get("score")
        clin.update(rating["counts"])
    rated = sum(1 for k in GLOBALS + COUNTS if clin.get(k) is not None)

    scorecard, globals_, behaviours = [], [], []
    for g in GLOBALS:
        o = agg["globals"][g]
        c = clin.get(g)
        d = _diff("global", c, o["mean"], g)
        scorecard.append({"item_id": g, "kind": "global", "label": labels[g],
                          "clinician": {"value": c}, "onolys": {"value": rep["globals"][g]["score"], **_stats(o)}, "diff": d})
        crit = (rating or {}).get("globals", {}).get(g, {}) if rating else {}
        support = [_line(turns, "t4", "What makes walking more important to you right now?")] if g == "cct" and crit.get("example") else []
        clinician = {"value": c}
        if crit.get("reason"):
            clinician["reason"] = crit["reason"]
        if crit.get("example"):
            clinician["example"] = {"at_s": crit["example"]["at_s"], "text": crit["example"]["text"]}
        gl = rep["globals"][g]
        globals_.append({
            "item_id": g,
            "onolys": {"score": gl["score"], "source": gl["source"], "reason": gl["reason"],
                       "evidence": [{k: e[k] for k in ("turn_id", "start", "end", "quote")} for e in gl["evidence"]]},
            "clinician": clinician, "diff": d,
            "explanation": _expl(g, "global", labels[g], d, o["mean"], c, gl["reason"],
                                 gl["evidence"], support)})
    for k in COUNTS:
        o = agg["counts"][k]
        c = clin.get(k)
        d = _diff("count", c, o["mean"], k)
        scorecard.append({"item_id": k, "kind": "count", "label": labels[k],
                          "clinician": {"value": c}, "onolys": {"value": o["mean"], **_stats(o)}, "diff": d})
        inst = [{"id": i["id"], "turn_id": i["turn_id"], "start": i["start"], "end": i["end"],
                 "quote": i["quote"], "rationale": i["rationale"]}
                for i in rep["instances"] if i["counted"] and i["code"] == k]
        entry: dict[str, Any] = {
            "item_id": k, "clinician_count": c, "onolys_count": _stats(o), "instances": inst,
            "instances_total": len(inst), "diff": d,
            "explanation": _expl(k, "count", labels[k], d, o["mean"], c, None, inst, [])}
        note = ((rating or {}).get("count_notes") or {}).get(k)
        if note:
            entry["clinician_note"] = note
        behaviours.append(entry)

    # summaries: clinician side from the same pack formulas; null when any input is missing
    summaries = [x.model_dump(mode="json") for x in compare_summaries(
        _PACK, {k: clin.get(k) for k in GLOBALS + COUNTS} if rating else None,
        PauditResult.model_validate(paudit).aggregate.summaries)]

    # reasons audit
    items, status, warnings = [], "skipped", [{"code": w["code"]} for w in paudit["warnings"]]
    if rating:
        status = "ran" if variant == "full" else "partial"
        if variant == "partial":
            warnings.append({"code": "reasons_audit_partial"})
        keys = ["cct", "sst", "partnership", "notes"] if variant == "full" else ["cct"]
        for key in keys:
            reason = rating["notes"] if key == "notes" else rating["globals"][key]["reason"]
            span, verdict, expl, ev = CLAIMS[key]
            assert span in reason, key
            items.append({"item_id": key, "reason": reason, "claims": [{
                "span": span, "verdict": verdict, "explanation": expl, "concerns": [],
                "evidence": [{"role": r, **_line(turns, t, sub)} for r, t, sub in ev]}]})

    tips = [{"rank": n, "item_id": item, "observation": obs,
             "quote": {"turn_id": t, "start": turns[t].index(q), "end": turns[t].index(q) + len(q), "text": q},
             "alternative": alt, "why_it_matters": why}
            for n, (item, t, q, obs, alt, why) in enumerate(TIPS, 1)]

    both = [s["diff"]["abs"] for s in scorecard if s["kind"] == "global" and s["diff"]["abs"] is not None]
    count_rows = [s for s in scorecard if s["kind"] == "count" and s["clinician"]["value"] is not None]
    aggregates = {
        "globals_compared": len(both),
        "avg_abs_global_difference": sum(both) / len(both) if both else None,
        "within_one_share": sum(1 for b in both if b <= 1) / len(both) if both else None,
        "counts_flagged": sum(1 for s in count_rows if s["diff"]["status"] == "flagged") if count_rows else None,
    }

    routes = {n: r["litellm_id"] for n, r in paudit["run_info"]["routes"].items()}
    models = {**routes, "tips": next(iter(routes.values())), **({"eaudit": next(iter(routes.values()))} if rating else {})}
    stt = SttRun.model_validate(transcript["stt_run"])
    pf = paudit["run_info"]["pack"]
    ri_eval = RunInfo(engine="evaluation", code_version="fixture", preset="fixture", stt=stt, pack=pf,
                      prompt_hashes={"engine:tips_templates": "0000000000000000"}, n_runs=1)
    ri_eaudit = RunInfo(engine="eaudit", code_version="fixture", preset="fixture", n_runs=1)
    layout = [{"section": s["id"], "title": s["label"], "items": s["items"]} for s in report_yaml["sections"]]

    return {
        "schema_version": "0.0.1",
        "request_id": f"req-fixture-{variant}",
        "created_at": CREATED_AT,
        "header": {
            "change_goal": paudit["change_goal"],
            "protocol": {"id": paudit["protocol"]["id"], "version": paudit["protocol"]["version"],
                         "pack_hash": paudit["protocol"]["pack_hash"], "label": f"{pack['id'].upper()} {pack['version']}"},
            "language": paudit["language"], "coded_span": paudit["coded_span"],
            "subject_speaker": speaker_map["subject"], "n_runs": 1, "models": models,
            "stt": transcript["stt_run"], "preset": "fixture", "code_version": "fixture",
            "params": {"n_runs": 1}, "has_clinician_rating": rating is not None,
            "rating_coverage": {"rated": rated, "total": len(GLOBALS) + len(COUNTS)}},
        "layout": layout, "scorecard": scorecard, "globals": globals_, "behaviours": behaviours,
        "summaries": summaries,
        "reasons_audit": {"status": status, "items": items},
        "tips": tips,
        "method": {
            "statement": "Onolys rated this session against the protocol using a language model; code checks every quote.",
            "limits": ["A language model can mis-rate; treat differences as prompts to look again.",
                       "Counts and ratings reflect the coded span only."],
            "not_official_miti_coding": True,
            "citation": pack["source"]["citation"].strip()},
        "aggregates": aggregates, "warnings": warnings,
        "run_info": {"evaluation": json.loads(ri_eval.model_dump_json()), "paudit": paudit["run_info"],
                     "eaudit": json.loads(ri_eaudit.model_dump_json()) if rating else None},
    }


def build_all() -> dict[str, dict[str, Any]]:
    return {f"report_{v}": build(v) for v in ("full", "partial", "no_rating")}


if __name__ == "__main__":
    for name, doc in build_all().items():
        text = json.dumps(doc, indent=2, ensure_ascii=False) + "\n"
        if "--write" in sys.argv:
            (OUT / f"{name}.json").write_text(text, encoding="utf-8")
        else:
            print(name, len(text))
