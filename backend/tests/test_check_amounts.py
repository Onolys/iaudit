import pytest
from check_helpers import claim, ev

from iaudit_backend.check.amounts import (
    compare_amounts,
    compare_kind,
    has_at_least_cue,
    polarity_reversals,
)
from iaudit_backend.check.models import ItemObs, JudgedEvidence
from iaudit_backend.config import Settings

CFG = Settings()


def q(raw, rate=None, guess=None, basis="relative"):
    return {"raw": raw, "rate_per_week": rate, "bucket_guess": guess, "basis": basis}


def judged(key="c0.1:e1", freq=(), sev=(), **kw):
    obs = ItemObs.model_validate(
        {"key": key, "relation": "entails", "frequency": list(freq), "severity": list(sev), **kw}
    )
    return JudgedEvidence(key=key, linked=ev(), obs=obs)


def fclaim(raw, **kw):
    return claim(f"Alex loses attention {raw}.", quantities=[raw], **kw)


def test_stronger_claim_inflates():
    f = compare_kind(fclaim("constantly"), [judged(freq=[q("Most meetings")])], "frequency", CFG)
    assert (f.direction, f.escalate, f.key) == ("inflates", False, "c0.1:e1")


def sclaim(*qs):
    return claim("Alex struggles.", quantities=[{"kind": k, "raw": r} for k, r in qs])


def test_weaker_claim_understates_never_escalates():
    f = compare_kind(sclaim(("severity", "mild")), [judged(sev=[q("severe")])], "severity", CFG)
    assert (f.direction, f.escalate) == ("understates", False)


def test_tie_and_missing_values_give_no_finding():
    assert (
        compare_kind(fclaim("most days"), [judged(freq=[q("usually")])], "frequency", CFG) is None
    )
    assert compare_kind(fclaim("most days"), [judged()], "frequency", CFG) is None
    assert compare_kind(claim("x"), [judged(freq=[q("daily")])], "frequency", CFG) is None


def test_adjacent_mixed_basis_is_ambiguous():
    # claim relative 'always' (5) vs evidence numeric 3.5/wk (often=3): d=+2 -> material
    # claim relative 'most' (4) vs evidence numeric 3.5/wk (3): adjacent + mixed basis -> benefit
    f = compare_kind(
        fclaim("most days"),
        [judged(freq=[q("3.5 times a week", 3.5, basis="numeric")])],
        "frequency",
        CFG,
    )
    assert f is None


def test_adjacent_near_a_bucket_boundary_is_ambiguous():
    c = claim("Alex naps.", quantities=["five times a week"])
    # claim numeric 5/wk (most=4); evidence numeric 3.8/wk (often=3) is within 15% of 4
    assert (
        compare_kind(c, [judged(freq=[q("3.8 a week", 3.8, basis="numeric")])], "frequency", CFG)
        is None
    )
    f = compare_kind(c, [judged(freq=[q("2 a week", 2.0, basis="numeric")])], "frequency", CFG)
    assert f.direction == "inflates"


def test_same_basis_pair_wins_over_a_closer_mixed_pair():
    # V1: claim relative always(5); evidence relative 4 (d=+1) and numeric 3.5/wk -> 3 (d=+2)
    c = fclaim("every meeting")
    it = judged(freq=[q("Most meetings"), q("three or four times a week", 3.5, basis="numeric")])
    f = compare_kind(c, [it], "frequency", CFG)
    assert (f.direction, f.escalate) == ("inflates", False)


def test_smallest_distance_across_items_gives_benefit_of_the_doubt():
    items = [judged("c0.1:e1", freq=[q("rarely")]), judged("c0.1:e2", freq=[q("every day")])]
    assert compare_kind(fclaim("every day"), items, "frequency", CFG) is None


def test_at_least_cue_blocks_understatement_only():
    assert has_at_least_cue("repeatedly") and not has_at_least_cue("some difficulty")
    c = claim(
        "Reports noted it.",
        quantities=[{"kind": "frequency", "raw": "repeatedly", "bucket": "often"}],
    )
    assert compare_kind(c, [judged(freq=[q("constantly")])], "frequency", CFG) is None
    assert compare_kind(c, [judged(freq=[q("never")])], "frequency", CFG).direction == "inflates"


def test_zero_bucket_escalates_and_large_gap_escalates():
    f = compare_kind(fclaim("sometimes"), [judged(freq=[q("never")])], "frequency", CFG)
    assert f.escalate
    f = compare_kind(fclaim("constantly"), [judged(freq=[q("rarely")])], "frequency", CFG)
    assert f.escalate  # gap of 4
    f = compare_kind(fclaim("constantly"), [judged(freq=[q("sometimes")])], "frequency", CFG)
    assert f.escalate  # gap of 3
    f = compare_kind(fclaim("constantly"), [judged(freq=[q("often")])], "frequency", CFG)
    assert not f.escalate


def test_model_guess_is_mixed_basis():
    c = fclaim("most days")
    assert (
        compare_kind(c, [judged(freq=[q("a fair bit", guess="often")])], "frequency", CFG) is None
    )
    f = compare_kind(
        fclaim("constantly"), [judged(freq=[q("a fair bit", guess="often")])], "frequency", CFG
    )
    assert f.direction == "inflates"


def test_material_threshold_is_configurable():
    cfg = Settings(check_step_material=2)
    assert (
        compare_kind(fclaim("every day"), [judged(freq=[q("most days")])], "frequency", cfg) is None
    )


def test_compare_amounts_covers_both_kinds():
    c = sclaim(("frequency", "every day"), ("severity", "severe"))
    it = judged(freq=[q("sometimes")], sev=[q("mild")])
    assert [(f.kind, f.direction) for f in compare_amounts(c, [it], CFG)] == [
        ("frequency", "inflates"),
        ("severity", "inflates"),
    ]


@pytest.mark.parametrize(
    "claim_pol,item_pol,exp,expect",
    [
        ("affirmed", "negated", "claim_subject", True),
        ("affirmed", "affirmed", "claim_subject", False),
        ("affirmed", "unclear", "claim_subject", False),
        ("negated", "affirmed", "claim_subject", True),
        ("affirmed", "negated", "other_person", False),
    ],
)
def test_polarity_reversal(claim_pol, item_pol, exp, expect):
    it = judged(polarity=item_pol, experiencer=exp)
    it.obs = it.obs.model_copy(update={"relation": "contradicts"})
    assert bool(polarity_reversals(claim("x", polarity=claim_pol), [it])) is expect


def test_polarity_ignores_entailing_items():
    assert polarity_reversals(claim("x"), [judged(polarity="negated")]) == []
