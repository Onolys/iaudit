"""SP03 T2 (R2, D11, D16, AC1): validate_rating, draft vs final. Code only; Issues carry no text."""

import copy
import importlib.metadata as md
import logging
import sys

import pytest
from paudit.pack import load_pack

from onolys_evaluation import Issue, is_no_rating, validate_rating

pytestmark = pytest.mark.unit


@pytest.fixture(scope="module")
def pack():
    return load_pack("miti@4.2.1")


def ids(pack, kind):
    return [i["id"] for i in pack.items if i["kind"] == kind]


@pytest.fixture
def full(pack):
    return {
        "change_goal": "cut down drinking",
        "coded_span": {"from_s": 0, "to_s": 1200},
        "globals": {
            g: {"score": 3, "reason": "r", "example": {"at_s": 12, "text": "t"}}
            for g in ids(pack, "global")
        },
        "counts": {c: {"count": 2, "note": "n"} for c in ids(pack, "count")},
        "notes": "some notes",
    }


def codes(issues):
    return {(i.path, i.code) for i in issues}


def test_full_card_valid_draft_and_final(pack, full):
    assert validate_rating(pack, full, False) == []
    assert validate_rating(pack, full, True) == []
    assert not is_no_rating(full)


def test_partial_two_globals_valid(pack):
    g = ids(pack, "global")[:2]
    card = {"change_goal": "x", "globals": {k: {"score": 4} for k in g}}
    assert validate_rating(pack, card, True) == []
    assert not is_no_rating(card)


def test_all_null_valid_and_no_rating(pack, full):
    card = {"change_goal": "x", "globals": {g: {"score": None} for g in ids(pack, "global")},
            "counts": {c: {"count": None} for c in ids(pack, "count")}, "notes": ""}
    assert validate_rating(pack, card, True) == []
    assert is_no_rating(card)
    assert is_no_rating({"change_goal": "x"})
    assert is_no_rating({"change_goal": "x", "notes": "   "})
    assert not is_no_rating({"notes": "hello"})
    assert not is_no_rating({"counts": {ids(pack, "count")[0]: {"count": 0}}})


def test_over_limit(pack, full):
    g, c = ids(pack, "global")[0], ids(pack, "count")[0]
    ok = copy.deepcopy(full)
    ok["globals"][g]["reason"] = "a" * 1000
    ok["globals"][g]["example"]["text"] = "a" * 1000
    ok["counts"][c]["note"] = "a" * 1000
    ok["notes"] = "a" * 3000
    assert validate_rating(pack, ok, True) == []
    bad = copy.deepcopy(ok)
    bad["globals"][g]["reason"] += "a"
    bad["globals"][g]["example"]["text"] += "a"
    bad["notes"] += "a"
    assert codes(validate_rating(pack, bad, False)) == {
        (f"globals/{g}/reason", "too_long"),
        (f"globals/{g}/example/text", "too_long"),
        ("notes", "too_long"),
    }
    bad["counts"][c]["note"] += "a"
    assert (f"counts/{c}/note", "too_long") in codes(validate_rating(pack, bad, True))


@pytest.mark.parametrize("score", [0, 6, -1])
def test_out_of_range_score(pack, score):
    g = ids(pack, "global")[0]
    got = validate_rating(pack, {"globals": {g: {"score": score}}}, False)
    assert codes(got) == {(f"globals/{g}/score", "out_of_range")}


def test_bad_score_and_count_types(pack):
    g, c = ids(pack, "global")[0], ids(pack, "count")[0]
    got = validate_rating(pack, {"globals": {g: {"score": "3"}},
                                 "counts": {c: {"count": 1.5}}}, False)
    assert codes(got) == {(f"globals/{g}/score", "invalid_type"),
                          (f"counts/{c}/count", "invalid_type")}
    assert codes(validate_rating(pack, {"counts": {c: {"count": -1}}}, False)) == {
        (f"counts/{c}/count", "out_of_range")}
    assert codes(validate_rating(pack, {"globals": {g: {"score": True}}}, False)) == {
        (f"globals/{g}/score", "invalid_type")}


def test_unknown_keys(pack):
    g, c = ids(pack, "global")[0], ids(pack, "count")[0]
    got = codes(validate_rating(pack, {
        "bogus": 1,
        "globals": {"nope": {"score": 3}, c: {"score": 3}, g: {"extra": 1}},
        "counts": {"nope2": {"count": 1}, g: {"count": 1}},
    }, False))
    assert got == {("bogus", "unknown_key"), ("globals/nope", "unknown_key"),
                   (f"globals/{c}", "unknown_key"), (f"globals/{g}/extra", "unknown_key"),
                   ("counts/nope2", "unknown_key"), (f"counts/{g}", "unknown_key")}


def test_bad_span(pack):
    assert codes(validate_rating(pack, {"coded_span": {"from_s": 50, "to_s": 10}}, False)) == {
        ("coded_span", "order")}
    assert codes(validate_rating(pack, {"coded_span": {"from_s": -1, "to_s": 10}}, False)) == {
        ("coded_span/from_s", "out_of_range")}
    assert validate_rating(pack, {"coded_span": None}, False) == []
    assert validate_rating(pack, {"coded_span": {"from_s": 5, "to_s": 5}}, False) == []


def test_draft_empty_change_goal_passes_final_fails(pack):
    for card in ({"change_goal": ""}, {"change_goal": "   "}, {}, {"change_goal": None}):
        assert validate_rating(pack, card, False) == []
        assert codes(validate_rating(pack, card, True)) == {("change_goal", "required")}


def test_not_an_object(pack):
    assert codes(validate_rating(pack, [1], False)) == {("", "invalid_type")}
    assert codes(validate_rating(pack, None, True)) == {("", "invalid_type")}


def test_issue_has_no_text(pack):
    secret = "SECRET-PHI-TEXT"
    g = ids(pack, "global")[0]
    got = validate_rating(pack, {"globals": {g: {"score": 9, "reason": secret * 200}},
                                 secret: secret}, True)
    assert got and all(isinstance(i, Issue) for i in got)
    assert all(secret not in i.code and secret * 2 not in i.path for i in got)


def test_no_text_logged(pack, caplog):
    secret = "SECRET-PHI-TEXT"
    g = ids(pack, "global")[0]
    card = {"change_goal": secret, "notes": secret,
            "globals": {g: {"score": 2, "reason": secret, "example": {"text": secret}}}}
    with caplog.at_level(logging.DEBUG, logger="iaudit"):
        validate_rating(pack, card, True)
        validate_rating(pack, {"notes": secret * 1000, "globals": {g: {"score": 99}}}, False)
    assert caplog.records, "expected a validation log event"
    assert secret not in caplog.text


def test_no_office_pdf_extractor_dependency():
    banned = ("openpyxl", "docx", "pdf", "xlrd", "pandas", "pypdf", "pdfminer", "fitz",
              "mammoth", "textract", "tika", "unstructured", "pymupdf", "xlsx", "odf")
    reqs = [r.split(";")[0] for r in (md.requires("onolys-evaluation") or [])]
    names = [r.replace("_", "-").lower() for r in reqs]
    assert names and not [n for n in names if any(b in n for b in banned)]
    assert not [m for m in sys.modules if m.split(".")[0] in {"openpyxl", "docx", "pypdf", "fitz"}]
