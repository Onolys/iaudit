"""07b data tests: gold labels round-trip, validate and follow the contract rules."""

import copy
import json

import pytest

from eaudit.models import ConcernType
from eval.adhd import DATA, load_spec
from eval.build_adhd import build
from eval.gold import GoldError, load_gold, parse_claim

FIXTURES = ["faithful", *[f"v{i}" for i in range(1, 9)], "v4-noroles"]


def request(fx):
    return json.loads((DATA / "requests" / f"{fx}.json").read_text(encoding="utf-8"))


def rows(fx):
    path = DATA / "gold" / f"{fx}.jsonl"
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


@pytest.mark.parametrize("fx", FIXTURES)
def test_gold_spans_round_trip_against_the_request(fx):
    text = request(fx)["assessment"][0]["text"]
    claims = load_gold(fx)
    assert [c.claim_id for c in claims] == [f"g{i}" for i in range(1, len(claims) + 1)]
    for c in claims:
        assert text[c.start : c.end] == c.claim_text
    for a, b in zip(claims, claims[1:], strict=False):
        assert a.end <= b.start


@pytest.mark.parametrize("fx", FIXTURES)
def test_gold_evidence_turns_exist_and_roles_are_in_roles_ok(fx):
    n = len(request(fx)["transcript"])
    for c in load_gold(fx):
        for e in c.evidence:
            assert 0 <= e.turn < n and e.role in e.roles_ok


def test_faithful_gold_is_ten_supported_controls():
    claims = load_gold("faithful")
    assert len(claims) == 10
    assert {c.verdict for c in claims} == {"supported"}
    assert {c.role_in_fixture for c in claims} == {"control"}
    assert all(c.concerns_required == [] and c.priority == "control" for c in claims)


@pytest.mark.parametrize("fx,count", [("v1", 10), ("v3", 11), ("v6", 9), ("v7", 9), ("v2", 10)])
def test_variant_gold_has_one_target_and_the_other_claims_are_controls(fx, count):
    claims = load_gold(fx)
    assert len(claims) == count
    targets = [c for c in claims if c.role_in_fixture == "target"]
    assert len(targets) == 1
    assert {c.role_in_fixture for c in claims if c is not targets[0]} == {"control"}


@pytest.mark.parametrize("v", load_spec()["variants"], ids=lambda v: v["id"])
def test_target_matches_the_spec_expectation_and_bucket(v):
    (t,) = [c for c in load_gold(v["id"]) if c.role_in_fixture == "target"]
    e = v["expected"]
    assert t.verdict == e["verdict"] and t.concerns_required == e["concerns_required"]
    assert t.concerns_allowed == e["concerns_allowed"]
    assert t.explanation_contains == e["explanation_contains"]
    first = e["concerns_required"][0]
    assert t.bucket == [c.value for c in ConcernType].index(first) + 1
    assert t.claim_text + "." == v["text"]


def test_priorities_follow_the_brainstorm_table():
    got = {f"v{i}": next(c for c in load_gold(f"v{i}") if c.role_in_fixture == "target")
           for i in range(1, 9)}  # fmt: skip
    assert [got[f"v{i}"].priority for i in range(1, 9)] == ["P0"] * 5 + ["P1"] * 3
    assert got["v1"].explanation_contains == ["inflates"]


def test_gold_evidence_matches_the_brainstorm_turns():
    def turns(fx):
        (t,) = [c for c in load_gold(fx) if c.role_in_fixture == "target"]
        return {(e.turn, e.role) for e in t.evidence}

    assert turns("v1") == {(3, "supporting")}
    assert turns("v2") == {(5, "contradicting")}
    assert turns("v3") == {(21, "contradicting")}
    assert {t for t, _ in turns("v4")} == {12, 13}
    assert turns("v5") == {(17, "qualifying")}
    assert {t for t, _ in turns("v6")} == {19, 23}


def test_v4_evidence_is_optional_so_empty_evidence_also_passes():
    (t,) = [c for c in load_gold("v4") if c.role_in_fixture == "target"]
    assert t.required_turns == []


@pytest.mark.parametrize("fx", FIXTURES)
def test_slots_validate_as_atomic_claims_with_scale_names(fx):
    for n, c in enumerate(load_gold(fx), 1):
        claim = c.atomic_claim(n)
        assert claim.span_hint == (c.start, c.end) and claim.segments == [c.claim_text]


def test_v4_noroles_strips_roles_and_expects_a_missing_role_warning():
    base, nr = request("v4"), request("v4-noroles")
    assert all("role" not in t for t in nr["transcript"])
    assert [{k: v for k, v in t.items() if k != "role"} for t in base["transcript"]] == nr[
        "transcript"
    ]
    assert nr["assessment"] == base["assessment"] and nr["request_id"] == "adhd-v4-noroles"
    (t,) = [c for c in load_gold("v4-noroles") if c.role_in_fixture == "target"]
    assert (t.verdict, t.concerns_required, t.expect_warnings) == (
        "insufficient_evidence", ["unsupported_claim"], ["ambiguous_speaker"],
    )  # fmt: skip
    exp = json.loads((DATA / "expected" / "v4-noroles.json").read_text(encoding="utf-8"))
    assert exp["concerns_required"] == ["unsupported_claim"]


def test_gold_files_contain_no_transcript_text():
    transcript = " ".join(t["text"].lower() for t in load_spec()["transcript"])
    for fx in FIXTURES:
        for r in rows(fx):
            for e in r["evidence"]:
                assert "text" not in e
    assert len(transcript) > 100


# -- the loader is strict --------------------------------------------------------------------


def good():
    return copy.deepcopy(rows("v1")[0])


@pytest.mark.parametrize(
    "mutate",
    [
        lambda r: r.update(surprise=1),
        lambda r: r.update(verdict="maybe"),
        lambda r: r.update(concerns_required=["not_a_concern"]),
        lambda r: r["evidence"][0].update(role="witness") if r["evidence"] else r.update(x=1),
        lambda r: r.update(gold_version=2),
        lambda r: r.update(priority="P9"),
        lambda r: r["slots"].update(bogus=1),
        lambda r: r["slots"]["quantities"].append(
            {"kind": "frequency", "raw": "x", "bucket": "severe", "rate_per_week": None}
        ),
        lambda r: r.update(expect_warnings=["nope"]),
    ],
)
def test_loader_rejects_unknown_fields_and_enums(mutate):
    r = good()
    mutate(r)
    with pytest.raises(GoldError):
        parse_claim(r)


def test_loader_enforces_contract_rules_two_to_six():
    r = good()
    r.update(verdict="supported", concerns_required=[], evidence=[
        {"turn": 3, "role": "contradicting", "roles_ok": ["contradicting"], "required": True}
    ])  # fmt: skip
    with pytest.raises(GoldError):
        parse_claim(r)
    r = good()
    r.update(verdict="contradicted")
    with pytest.raises(GoldError):
        parse_claim(r)  # no contradicting evidence
    r = good()
    r.update(concerns_required=[])
    with pytest.raises(GoldError):
        parse_claim(r)  # partially_supported without a concern
    r = good()
    r.update(verdict="insufficient_evidence", evidence=[
        {"turn": 3, "role": "contradicting", "roles_ok": ["contradicting"], "required": True}
    ])  # fmt: skip
    with pytest.raises(GoldError):
        parse_claim(r)
    r = good()
    r.update(verdict="out_of_scope")
    with pytest.raises(GoldError):
        parse_claim(r)


def test_gold_is_part_of_the_reproducible_build():
    out = build()
    assert {f"gold/{fx}.jsonl" for fx in FIXTURES} <= set(out)
