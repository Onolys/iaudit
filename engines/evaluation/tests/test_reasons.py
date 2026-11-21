"""R3/D2/D18/AC2/AC4: reasons-audit request mapping, evidence mapping, pack `evaluation:` block.
eaudit is stubbed: only the pure mapping functions run, no model call."""

from pathlib import Path

import pytest
import yaml
from eaudit.models import AuditResponse, ConcernType
from onolys_core.transcript import Transcript, Turn
from paudit.pack import load_pack

from onolys_evaluation.reasons import (
    NOTES_ID,
    build_reasons_request,
    map_reasons_response,
    reasons_profile,
    support_lines,
)

pytestmark = pytest.mark.unit

PACK_DIR = Path(__file__).resolve().parents[3] / "protocols" / "miti-4.2.1"

KEEP = {
    "unsupported_claim", "contradictory_evidence", "wrong_attribution", "negation_reversal",
    "question_as_answer", "frequency_severity_inflation", "meaning_shift", "context_stripping",
    "correction_ignored", "certainty_inflation",
}
SUPPRESS = {
    "timeframe_mismatch", "quantity_mismatch", "calculation_error", "opinion_as_fact",
    "unsupported_causal_link", "unsupported_inference", "conflicting_accounts_flattened",
}


@pytest.fixture(scope="module")
def pack():
    return load_pack(PACK_DIR)


@pytest.fixture()
def tr():
    return Transcript(turns=[
        Turn(id="t1", speaker="B", text="I want to walk more.", start_ms=0),
        Turn(id="t2", speaker="A", text="What makes that important?", start_ms=65000),
        Turn(id="t3", speaker="B", text="My blood pressure.", start_ms=70000),
        Turn(id="t4", speaker="C", text="Someone else.", start_ms=71000),
    ])


SMAP = {"subject": "A", "other": "B"}


def card():
    return {
        "globals": {
            "cct": {"score": 4, "reason": "Asked what was important.",
                    "example": {"at_s": 65, "text": "What makes that important?"}},
            "sst": {"score": 3},
            "partnership": {"score": 5, "reason": "Asked permission."},
            "empathy": {"score": 2, "example": {"text": "no time given"}},
        },
        "counts": {"sr": {"count": 3, "note": "Three simple reflections."}, "cr": {"count": 1}},
        "notes": "A collaborative session.",
    }


def test_three_reasons_three_sections_display_only_scores(pack, tr):
    rating = {"globals": {k: v for k, v in card()["globals"].items() if k != "empathy"
                          and k != "sst"} | {"sst": {"score": 3, "reason": "Moved on."}}}
    built = build_reasons_request(pack, tr, SMAP, rating)
    secs = built.request.assessment
    assert [s.id for s in secs] == ["cct", "sst", "partnership"]
    assert [s.score for s in secs] == [4, 3, 5]
    assert secs[0].label == "Cultivating Change Talk"
    assert secs[2].text == "Asked permission."
    assert built.section_ids == ["cct", "sst", "partnership"]


def test_example_line_appended(pack, tr):
    secs = build_reasons_request(pack, tr, SMAP, card()).request.assessment
    by = {s.id: s for s in secs}
    assert by["cct"].text == (
        "Asked what was important.\nExample at 01:05: What makes that important?")
    assert by["empathy"].text == "Example: no time given"  # example-only item still audited


def test_notes_section_and_count_notes(pack, tr):
    secs = build_reasons_request(pack, tr, SMAP, card()).request.assessment
    assert secs[-1].id == NOTES_ID == "notes"
    assert secs[-1].label == "Additional notes / evaluation reasoning"
    assert secs[-1].text == "A collaborative session."
    sr = next(s for s in secs if s.id == "sr")
    assert sr.text == "Three simple reflections." and sr.score == 3


def test_no_section_without_text(pack, tr):
    secs = build_reasons_request(pack, tr, SMAP, card()).request.assessment
    ids = [s.id for s in secs]
    assert "sst" not in ids and "cr" not in ids
    blank = {"globals": {"cct": {"score": 4, "reason": "  "}}, "notes": "   "}
    assert build_reasons_request(pack, tr, SMAP, blank) is None
    assert build_reasons_request(pack, tr, SMAP, None) is None


def test_roles_mapped_from_speaker_map(pack, tr):
    built = build_reasons_request(pack, tr, SMAP, card())
    roles = [(t.id, t.role.value) for t in built.request.transcript]
    assert roles == [("t1", "respondent"), ("t2", "interviewer"), ("t3", "respondent"),
                     ("t4", "respondent")]
    assert built.sent_turn_ids == ["t1", "t2", "t3", "t4"]
    assert built.request.transcript[1].timestamp == "01:05"


def test_profile_attached(pack, tr):
    built = build_reasons_request(pack, tr, SMAP, card())
    assert set(built.request.profile.suppress_concerns) == {ConcernType(c) for c in SUPPRESS}
    assert "interviewer's own rating" in built.request.profile.context_note


def _resp(claims):
    return AuditResponse.model_validate({"status": "complete", "warnings": [], "claims": claims})


def _claim(i, sec, a, b, ev, verdict="supported", concerns=()):
    return {"id": f"c{i}", "span": {"start": {"index": sec, "char": a},
                                    "end": {"index": sec, "char": b}},
            "verdict": verdict, "explanation": "x", "concerns": [{"type": c, "group": "not_in_interview", "explanation": "x", "evidence_ids": []}
                         for c in concerns], "evidence": ev}


def _ev(role, si, sc, ei, ec):
    return {"id": "e", "role": role,
            "span": {"start": {"index": si, "char": sc}, "end": {"index": ei, "char": ec}}}


def test_one_turn_evidence_quote_equals_transcript_substring(pack, tr):
    built = build_reasons_request(pack, tr, SMAP, card())
    claims = [_claim(1, 0, 0, 5, [_ev("supporting", 1, 0, 1, 11)])]
    items = map_reasons_response(_resp(claims), built, tr)
    assert [i.item_id for i in items] == built.section_ids
    cl = items[0].claims[0]
    assert cl.span == "Asked"  # claim span read from the section text
    (e,) = cl.evidence
    assert (e.turn_id, e.start, e.end, e.role) == ("t2", 0, 11, "supporting")
    assert e.quote == tr.turns[1].text[0:11] == "What makes "


def test_three_turn_span_splits_per_turn(pack, tr):
    built = build_reasons_request(pack, tr, SMAP, card())
    claims = [_claim(1, 1, 0, 5, [_ev("contradicting", 0, 7, 2, 4)], "contradicted",
                     ["unsupported_claim"])]
    items = map_reasons_response(_resp(claims), built, tr)
    item = next(i for i in items if i.item_id == "partnership")
    cl = item.claims[0]
    assert cl.concerns == ["unsupported_claim"] and cl.verdict == "contradicted"
    got = [(e.turn_id, e.start, e.end, e.quote, e.role) for e in cl.evidence]
    t = [x.text for x in tr.turns]
    assert got == [
        ("t1", 7, len(t[0]), t[0][7:], "contradicting"),
        ("t2", 0, len(t[1]), t[1], "contradicting"),
        ("t3", 0, 4, t[2][:4], "contradicting"),
    ]


def test_claim_in_notes_section_resolves_to_notes(pack, tr):
    built = build_reasons_request(pack, tr, SMAP, card())
    notes_idx = built.section_ids.index("notes")
    items = map_reasons_response(_resp([_claim(1, notes_idx, 0, 7, [])]), built, tr)
    n = next(i for i in items if i.item_id == "notes")
    assert n.reason == "A collaborative session." and n.claims[0].span == "A colla"


def test_out_of_range_pointers_are_dropped(pack, tr):
    built = build_reasons_request(pack, tr, SMAP, card())
    claims = [_claim(1, 0, 0, 5, [_ev("supporting", 99, 0, 99, 3)]), _claim(2, 99, 0, 2, [])]
    items = map_reasons_response(_resp(claims), built, tr)
    assert len(items[0].claims) == 1 and items[0].claims[0].evidence == []
    assert sum(len(i.claims) for i in items) == 1


def test_support_lines_only_from_supported_claims(pack, tr):
    built = build_reasons_request(pack, tr, SMAP, card())
    claims = [
        _claim(1, 0, 0, 5, [_ev("supporting", 1, 0, 1, 11), _ev("contradicting", 0, 0, 0, 3)]),
        _claim(2, 0, 0, 5, [_ev("supporting", 2, 0, 2, 4)], "contradicted"),
    ]
    items = map_reasons_response(_resp(claims), built, tr)
    lines = support_lines(items, "cct")
    assert [(x.turn_id, x.quote) for x in lines] == [("t2", "What makes ")]
    assert type(lines[0]).__name__ == "Line" and support_lines(items, "empathy") == []


def test_pack_suppress_list_matches_r3_table():
    ra = yaml.safe_load((PACK_DIR / "pack.yaml").read_text())["evaluation"]["reasons_audit"]
    assert set(ra["suppress_concerns"]) == SUPPRESS
    assert len(ra["suppress_concerns"]) == len(SUPPRESS)
    assert KEEP.isdisjoint(ra["suppress_concerns"])
    assert KEEP | SUPPRESS == {c.value for c in ConcernType}
    assert ra["context_note"].startswith("This is the interviewer's own rating of their conduct.")


def test_profile_validates_against_enum(pack):
    assert reasons_profile(pack).suppress_concerns == [ConcernType(c) for c in
                                                       pack.data["evaluation"]["reasons_audit"][
                                                           "suppress_concerns"]]
