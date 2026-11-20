import pytest
from check_helpers import claim, ev

from eaudit.check.models import FlagObs, ItemObs, JudgedEvidence
from eaudit.check.synth import apply_timeframe, timeframe_mismatch


def judged(tf, rel="entails", conf="high", key="c0.1:e1"):
    obs = ItemObs(key=key, relation=rel, timeframe=tf, conf=conf)
    return JudgedEvidence(key=key, linked=ev(), obs=obs)


@pytest.mark.parametrize(
    "c,i,expect",
    [
        ("current", "past", True),
        ("current", "childhood", True),
        ("future", "past", True),
        ("past", "current", True),
        ("childhood", "current", True),
        ("childhood", "past", False),
        ("current", "current", False),
        ("current", "unspecified", False),
        ("unspecified", "past", False),
        ("current", "hypothetical", True),
        ("childhood", "hypothetical", True),
        ("hypothetical", "hypothetical", False),
    ],
)
def test_mismatch_table(c, i, expect):
    assert timeframe_mismatch(c, i) is expect


def test_mismatched_item_is_demoted():
    c = claim("He currently forgets.", timeframe_explicit=True)
    it = judged("childhood", conf="medium")
    assert apply_timeframe(c, [it], []) == 1 and it.demote == "timeframe"


def test_contradicting_item_from_another_period_is_demoted_too():
    c = claim("He forgets.", timeframe_explicit=True)
    it = judged("past", rel="contradicts")
    apply_timeframe(c, [it], [])
    assert it.demote == "timeframe"


def test_not_addresses_is_left_alone():
    it = judged("past", rel="not_addresses")
    assert apply_timeframe(claim("x", timeframe_explicit=True), [it], []) == 0


def test_implicit_current_claim_needs_high_confidence():
    c = claim("He forgets.")  # timeframe current, not stated
    low, high = judged("past", conf="medium"), judged("past", conf="high", key="c0.1:e2")
    apply_timeframe(c, [low, high], [])
    assert low.demote is None and high.demote == "timeframe"


def test_verifier_flag_demotes_cited_keys_with_the_same_gate():
    flag = lambda conf: FlagObs(type="timeframe_mismatch", keys=["c0.1:e1"], conf=conf)  # noqa: E731
    it = judged("unspecified")
    apply_timeframe(claim("x", timeframe_explicit=True), [it], [flag("medium")])
    assert it.demote == "timeframe"
    it = judged("unspecified")
    apply_timeframe(claim("x"), [it], [flag("medium")])
    assert it.demote is None
    apply_timeframe(claim("x"), [it], [flag("high")])
    assert it.demote == "timeframe"


def test_timeframe_flag_without_keys_applies_to_all_judged_items():
    it = judged("unspecified")
    apply_timeframe(
        claim("x", timeframe_explicit=True), [it], [FlagObs(type="timeframe_mismatch", conf="high")]
    )
    assert it.demote == "timeframe"
