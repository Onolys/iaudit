"""Generates the three report fixtures under protocols/miti-4.2.1/fixtures/evaluation/ from the
synthetic transcript and the stub-generated PauditResult in the same folder. All text is
SYNTHETIC; every quote is cut from the fixture transcript by substring, so offsets are exact
(code points). The reports are produced by the real `build_report`; this module only supplies the
inputs (rating, mapped reasons-audit items, tips).

    uv run --package onolys-evaluation python engines/evaluation/tests/_make_fixtures.py --write

A test keeps the committed JSON in sync with this module."""

import json
import sys
from pathlib import Path
from typing import Any

from onolys_core.run_info import RunInfo
from onolys_core.transcript import Transcript
from paudit.pack import load_pack
from paudit.result import PauditResult

from onolys_evaluation.api import TipsArtifact, build_report
from onolys_evaluation.hashes import evaluation_prompt_hashes
from onolys_evaluation.report import AuditItem, Tip

REPO = Path(__file__).resolve().parents[3]
PACK = REPO / "protocols" / "miti-4.2.1"
OUT = PACK / "fixtures" / "evaluation"
_PACK = load_pack(PACK)
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
    "counts": {k: ({"count": n, "note": "Counted the short repeats of the client's words."}
                   if k == "sr" else {"count": n}) for k, n in
               {"gi": 2, "persuade": 0, "persuade_permission": 1, "question": 6, "sr": 4,
                "cr": 3, "affirm": 2, "seek_collab": 2, "emphasize_autonomy": 1,
                "confront": 0}.items()},
    "notes": "A collaborative session. The client left with a plan for three lunch walks.",
}
PARTIAL_RATING: dict[str, Any] = {
    "globals": {
        "cct": {"score": 4, "reason": "The clinician asked what made walking important, then kept returning to the client's reasons."},
        "partnership": {"score": 5},
    },
    "counts": {"question": {"count": 6}, "cr": {"count": 3}},
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


def inputs(variant: str) -> dict[str, Any]:
    """Keyword arguments for `build_report` for one fixture variant."""
    transcript_doc = _load("transcript.json")
    turns = {t["id"]: t["text"] for t in transcript_doc["turns"]}
    rating = {"full": FULL_RATING, "partial": PARTIAL_RATING, "no_rating": None}[variant]
    items: list[AuditItem] = []
    if rating:
        keys = ["cct", "sst", "partnership", "notes"] if variant == "full" else ["cct"]
        for key in keys:
            reason = rating["notes"] if key == "notes" else rating["globals"][key]["reason"]
            span, verdict, expl, ev = CLAIMS[key]
            assert span in reason, key
            items.append(AuditItem.model_validate({"item_id": key, "reason": reason, "claims": [{
                "span": span, "verdict": verdict, "explanation": expl, "concerns": [],
                "evidence": [{"role": r, **_line(turns, t, sub)} for r, t, sub in ev]}]}))
    tips = [Tip(rank=n, item_id=item, observation=obs, alternative=alt, why_it_matters=why,
                quote={"turn_id": t, "start": turns[t].index(q),
                       "end": turns[t].index(q) + len(q), "text": q})
            for n, (item, t, q, obs, alt, why) in enumerate(TIPS, 1)]
    paudit = _load("paudit_result.json")
    route = next(iter(paudit["run_info"]["routes"].values()))["litellm_id"]
    return {
        "pack": _PACK,
        "transcript": Transcript.model_validate(transcript_doc),
        "speaker_map": _load("speaker_map.json"),
        "params": {"n_runs": 1, "preset": "fixture", "code_version": "fixture"},
        "rating": rating,
        "paudit_result": PauditResult.model_validate(paudit),
        "reasons_items": items if rating else None,
        "reasons_partial": variant == "partial",
        "tips": TipsArtifact(valid=tips, proposals=[]),
        "models": {"tips": route, **({"eaudit": route} if rating else {})},
        "prompt_hashes": evaluation_prompt_hashes(_PACK),
        "eaudit_run_info": RunInfo(engine="eaudit", code_version="fixture", preset="fixture")
        if rating else None,
        "request_id": f"req-fixture-{variant}",
        "created_at": CREATED_AT,
    }


def build(variant: str) -> dict[str, Any]:
    return json.loads(build_report(**inputs(variant)).model_dump_json())


def build_all() -> dict[str, dict[str, Any]]:
    return {f"report_{v}": build(v) for v in ("full", "partial", "no_rating")}


if __name__ == "__main__":
    for name, doc in build_all().items():
        text = json.dumps(doc, indent=2, ensure_ascii=False) + "\n"
        if "--write" in sys.argv:
            (OUT / f"{name}.json").write_text(text, encoding="utf-8")
        else:
            print(name, len(text))
