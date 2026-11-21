"""MITI 4.2.1 pack data (protocols/miti-4.2.1): loads cleanly, caps cite a manual page,
formulas parse and match the manual, and the one rules.py hook behaves."""

import json
import re
from pathlib import Path

import pytest
from onolys_core.transcript import Turn

from paudit.formula import check, evaluate, label_for
from paudit.hooks import load_hooks
from paudit.pack import PROMPT_FILES, load_pack
from paudit.prepare import OTHER, SUBJECT, CheckInput, RoleTurn

pytestmark = pytest.mark.unit

PROTOCOLS = Path(__file__).resolve().parents[3] / "protocols"
GLOBALS = ["cct", "sst", "partnership", "empathy"]
CODES = ["gi", "persuade", "persuade_permission", "question", "sr", "cr", "affirm",
         "seek_collab", "emphasize_autonomy", "confront"]


@pytest.fixture(scope="module")
def pack():
    return load_pack("miti@4.2.1", protocols_dir=PROTOCOLS)


def item(pack, iid):
    return next(i for i in pack.items if i["id"] == iid)


def test_loads_and_has_all_items(pack):
    assert (pack.id, pack.version, pack.pack_format) == ("miti", "4.2.1", "0.0.1")
    assert [i["id"] for i in pack.items if i["kind"] == "global"] == GLOBALS
    assert [i["id"] for i in pack.items if i["kind"] == "count"] == CODES
    assert pack.data["speaker_roles"] == {"subject": "clinician", "other": "client"}
    assert pack.data["volley"] == {"breaks_on": "other_speaker", "min_other_words": 0}
    assert pack.pack_hash


def test_prompt_files_present_and_json_valid(pack):
    for name in PROMPT_FILES:
        text = (pack.root / "prompts" / name).read_text()
        assert text.strip()
        if name.endswith(".json"):
            shots = json.loads(text)
            assert isinstance(shots, list) and shots
            assert all(s.get("synthetic") is True for s in shots)


def test_globals_scale_and_evidence(pack):
    for g in GLOBALS:
        it = item(pack, g)
        assert it["scale"] == {"min": 1, "max": 5, "default": 3}
        assert it["evidence_min"] >= 1


def test_definitions_cite_manual_pages(pack):
    for it in pack.items:
        assert re.search(r"manual p+\. ?\d+", it["definition"], re.I), it["id"]


def test_every_cap_cites_a_manual_page(pack):
    caps = [(i["id"], c) for i in pack.items for c in i.get("caps", [])]
    assert caps, "manual p. 4 states a ceiling for a 5 with prominent poor practice"
    for iid, cap in caps:
        assert cap["when"] == "poor_practice_cited"
        assert cap["max"] == 4
        assert re.search(r"manual p\. ?\d+", cap["source"]), iid
    assert all(item(pack, iid)["kind"] == "global" for iid, _ in caps)


def test_rules(pack):
    assert pack.data["rules"] == [
        {"kind": "one_code_per_utterance"},
        {"kind": "max_per_unit", "unit": "volley", "code": "any", "n": 1},
        {"kind": "exclusive_group", "unit": "volley", "codes": ["sr", "cr"],
         "precedence": ["cr", "sr"]},
    ]


def test_input_checks(pack):
    got = {c["id"]: (c["kind"], c["value"], c["severity"]) for c in pack.data["input_checks"]}
    assert got["duration_max"] == ("duration_max", 25, "error")
    assert got["duration_min"] == ("duration_min", 10, "warn")
    assert got["change_goal"] == ("param_required", "change_goal", "error")
    assert got["min_subject_turns"] == ("min_subject_turns", 5, "error")
    assert got["min_other_turns"] == ("min_other_turns", 3, "error")


SUMMARIES = {
    "technical": ("(cct+sst)/2", 3, 4),
    "relational": ("(partnership+empathy)/2", 3.5, 4),
    "pct_cr": ("cr/(sr+cr)", 0.4, 0.5),
    "reflection_question_ratio": ("(sr+cr)/question", 1, 2),
}


def test_summaries_match_manual(pack):
    by_id = {s["id"]: s for s in pack.data["summaries"]}
    for sid, (expr, fair, good) in SUMMARIES.items():
        s = by_id[sid]
        assert s["expr"] == expr
        assert s["reference"] == {"fair": fair, "good": good, "direction": "higher_better"}
    assert by_id["total_mia"]["expr"] == "seek_collab+affirm+emphasize_autonomy"
    assert by_id["total_mina"]["expr"] == "confront+persuade"
    assert "reference" not in by_id["total_mia"] and "reference" not in by_id["total_mina"]
    ids = {i["id"] for i in pack.items}
    for s in by_id.values():
        assert check(s["expr"]) <= ids


def test_summary_values_and_labels(pack):
    by_id = {s["id"]: s for s in pack.data["summaries"]}
    vals = {"cct": 4, "sst": 3, "partnership": 4, "empathy": 3, "sr": 2, "cr": 2, "question": 2}
    tech = evaluate(by_id["technical"]["expr"], vals)
    assert tech == 3.5 and label_for(tech, by_id["technical"]["reference"]) == "fair"
    pct = evaluate(by_id["pct_cr"]["expr"], vals)
    assert pct == 0.5 and label_for(pct, by_id["pct_cr"]["reference"]) == "good"
    assert evaluate(by_id["pct_cr"]["expr"], {"sr": 0, "cr": 0}) is None
    assert evaluate(by_id["reflection_question_ratio"]["expr"], {**vals, "question": 0}) is None


def test_compare_covers_every_item_with_a_kind(pack):
    cmp = pack.data["compare"]
    assert set(cmp) == set(GLOBALS + CODES)
    for g in GLOBALS:
        assert cmp[g] == {"kind": "score_diff", "differs_at": 1, "within": 1}
    for c in CODES:
        assert cmp[c] == {"kind": "count_diff", "flag_abs": 2, "flag_rel": 0.25}
    assert set(pack.data["evaluation"]) == {"tone", "reasons_audit"}


def test_report_stub_lists_known_ids(pack):
    listed = [x for s in pack.report["sections"] for x in s["items"]]
    assert set(GLOBALS + CODES) <= set(listed)
    assert all({"id", "label", "items"} <= set(s) for s in pack.report["sections"])


# --- rules.py hook -------------------------------------------------------------------------

def rt(i, role):
    return RoleTurn(Turn(id=f"t{i}", speaker="A" if role == SUBJECT else "B", text="synthetic"),
                    role)


def run_hook(pack, roles):
    hooks = load_hooks(pack)
    assert hooks.check_input and hooks.validate_codes is None and hooks.compute_summary is None
    turns = [rt(i, r) for i, r in enumerate(roles)]
    return hooks.check_input(CheckInput(turns, {}, None), pack.data)


def test_hook_warns_when_clinician_opens_without_client_speech(pack):
    out = run_hook(pack, [SUBJECT, OTHER, SUBJECT, OTHER])
    assert len(out) == 1
    assert out[0]["code"] == "reflection_before_client_speech"
    assert out[0]["severity"] == "info"
    assert "t0" in out[0]["detail"]


def test_hook_silent_when_client_speaks_first(pack):
    assert run_hook(pack, [OTHER, SUBJECT, OTHER, SUBJECT]) == []


def test_hook_warns_once_for_consecutive_opening_turns(pack):
    out = run_hook(pack, [SUBJECT, SUBJECT, OTHER, SUBJECT])
    assert len(out) == 1 and "t0" in out[0]["detail"] and "t1" in out[0]["detail"]


def test_hook_no_turns(pack):
    assert run_hook(pack, []) == []
