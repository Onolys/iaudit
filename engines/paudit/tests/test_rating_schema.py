"""MITI 4.2.1 rating card schema (protocols/miti-4.2.1/rating.schema.json) + parity with the pack."""

import json
from pathlib import Path

import pytest
import yaml
from jsonschema import Draft202012Validator

pytestmark = pytest.mark.unit

PROTOCOL = Path(__file__).resolve().parents[3] / "protocols" / "miti-4.2.1"
SCHEMA_PATH = PROTOCOL / "rating.schema.json"
PACK_PATH = PROTOCOL / "pack.yaml"

GLOBALS = ["cct", "sst", "partnership", "empathy"]
COUNTS = [
    "gi", "persuade", "persuade_permission", "question", "sr", "cr",
    "affirm", "seek_collab", "emphasize_autonomy", "confront",
]


@pytest.fixture(scope="module")
def validator():
    schema = json.loads(SCHEMA_PATH.read_text())
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema)


def full_card():
    return {
        "change_goal": "cut down drinking",
        "coded_span": {"from_s": 0, "to_s": 600},
        "globals": {
            g: {"score": 3, "reason": "r", "example": {"at_s": 12, "text": "t"}} for g in GLOBALS
        },
        "counts": {c: {"count": 2, "note": "n"} for c in COUNTS},
        "notes": "extra",
    }


def errors(validator, card):
    return list(validator.iter_errors(card))


def test_accepts_full_card(validator):
    assert errors(validator, full_card()) == []


@pytest.mark.parametrize("card", [
    {},
    {"change_goal": "x"},
    {"coded_span": None},
    {"globals": {"cct": {"score": None}}},
    {"globals": {"empathy": {"score": 5, "reason": "r"}}},
    {"counts": {"gi": {"count": None}, "cr": {"count": 0}}},
    {"counts": {"sr": {"count": 3}}, "notes": None},
])
def test_accepts_partial_cards(validator, card):
    assert errors(validator, card) == []


@pytest.mark.parametrize("score", [0, 6, -1, 2.5, "3"])
def test_rejects_bad_score(validator, score):
    assert errors(validator, {"globals": {"cct": {"score": score}}})


@pytest.mark.parametrize("count", [-1, 1.5, "2"])
def test_rejects_bad_count(validator, count):
    assert errors(validator, {"counts": {"gi": {"count": count}}})


def test_rejects_unknown_keys(validator):
    assert errors(validator, {"globals": {"nope": {"score": 3}}})
    assert errors(validator, {"counts": {"nope": {"count": 1}}})
    assert errors(validator, {"bogus": 1})


def test_string_limits(validator):
    ok, bad = "x" * 1000, "x" * 1001
    assert errors(validator, {"globals": {"cct": {"reason": ok, "example": {"text": ok}}}}) == []
    assert errors(validator, {"counts": {"gi": {"note": ok}}}) == []
    assert errors(validator, {"notes": "x" * 3000}) == []
    assert errors(validator, {"globals": {"cct": {"reason": bad}}})
    assert errors(validator, {"globals": {"cct": {"example": {"text": bad}}}})
    assert errors(validator, {"counts": {"gi": {"note": bad}}})
    assert errors(validator, {"notes": "x" * 3001})


def test_schema_keys_are_the_miti_ids(validator):
    props = validator.schema["properties"]
    assert list(props["globals"]["properties"]) == GLOBALS
    assert list(props["counts"]["properties"]) == COUNTS
    assert set(props["coded_span"]["properties"]) == {"from_s", "to_s"}


@pytest.mark.skipif(
    not PACK_PATH.is_file(),
    reason="protocols/miti-4.2.1/pack.yaml not present yet (lands in SP02 Task 6); runs automatically once it exists",
)
def test_parity_with_real_pack(validator):
    items = yaml.safe_load(PACK_PATH.read_text())["items"]
    props = validator.schema["properties"]
    for section, kind in (("globals", "global"), ("counts", "count")):
        want = {i["id"] for i in items if i["kind"] == kind}
        assert set(props[section]["properties"]) == want, section
    from paudit.pack import load_pack

    assert load_pack("miti@4.2.1", protocols_dir=PROTOCOL.parent).id == "miti"
