"""Specific taxonomy concerns explain a discrepancy once and allow vetted revisions."""

import itertools

import pytest
from check_helpers import claim, ev

from eaudit.check.models import Concern, FlagObs, ItemObs, JudgedEvidence, Signals
from eaudit.check.synth import decide, dedup
from eaudit.check.templates import REVISABLE, vet_revision
from eaudit.config import Settings
from eaudit.models import ConcernType as CT
from eaudit.models import Verdict

YIELDS = (
    (CT.meaning_shift, CT.contradictory_evidence),
    (CT.opinion_as_fact, CT.certainty_inflation),
    (CT.opinion_as_fact, CT.unsupported_causal_link),
    (CT.opinion_as_fact, CT.unsupported_inference),
    (CT.unsupported_causal_link, CT.unsupported_inference),
    (CT.calculation_error, CT.quantity_mismatch),
)


@pytest.mark.parametrize("winner,loser", YIELDS)
@pytest.mark.parametrize("keys", [("a", "a"), (None, "a"), ("a", None)])
def test_specific_concern_suppresses_shared_or_unlocated_discrepancy(winner, loser, keys):
    winner_keys, loser_keys = ([key] if key else [] for key in keys)
    concerns = [Concern(winner, winner_keys), Concern(loser, loser_keys)]
    for ordered in itertools.permutations(concerns):
        assert [(c.type, c.keys) for c in dedup(list(ordered))] == [(winner, winner_keys)]


@pytest.mark.parametrize("winner,loser", YIELDS)
def test_different_items_keep_both_discrepancies(winner, loser):
    out = dedup([Concern(winner, ["a"]), Concern(loser, ["b"])])
    assert {(c.type, tuple(c.keys)) for c in out} == {(winner, ("a",)), (loser, ("b",))}


@pytest.mark.parametrize(
    "earlier",
    [CT.wrong_attribution, CT.negation_reversal, CT.frequency_severity_inflation, CT.quantity_mismatch],
)
def test_existing_specific_chain_types_suppress_meaning_shift(earlier):
    concerns = [Concern(CT.meaning_shift, ["a"]), Concern(earlier, ["a"])]
    assert [c.type for c in dedup(concerns)] == [earlier]


def test_opinion_explains_a_shared_certainty_causal_and_inference_discrepancy_once():
    concerns = [
        Concern(CT.certainty_inflation, ["a"]),
        Concern(CT.unsupported_causal_link, ["a"]),
        Concern(CT.unsupported_inference, ["a"]),
        Concern(CT.opinion_as_fact, ["a"]),
    ]
    assert [c.type for c in dedup(concerns)] == [CT.opinion_as_fact]


def test_concerns_suppressed_by_calculation_do_not_hide_a_separate_meaning_discrepancy():
    concerns = [
        Concern(CT.quantity_mismatch, ["a"]),
        Concern(CT.meaning_shift, ["a"]),
        Concern(CT.calculation_error, ["a"]),
    ]
    assert [c.type for c in dedup(concerns)] == [CT.calculation_error, CT.meaning_shift]


def test_independent_new_concerns_follow_public_enum_order():
    concerns = [
        Concern(CT.unsupported_inference, ["inference"]),
        Concern(CT.meaning_shift, ["meaning"]),
        Concern(CT.calculation_error, ["calculation"]),
        Concern(CT.opinion_as_fact, ["opinion"]),
        Concern(CT.quantity_mismatch, ["quantity"]),
        Concern(CT.certainty_inflation, ["certainty"]),
    ]
    assert [c.type for c in dedup(concerns)] == [
        CT.certainty_inflation,
        CT.quantity_mismatch,
        CT.opinion_as_fact,
        CT.calculation_error,
        CT.meaning_shift,
        CT.unsupported_inference,
    ]


@pytest.mark.parametrize("kind", [CT.opinion_as_fact, CT.meaning_shift, CT.unsupported_inference])
@pytest.mark.parametrize("verdict", [Verdict.partially_supported, Verdict.contradicted])
def test_new_checkable_concerns_allow_vetted_revisions(kind, verdict):
    revision = "Some panel members raised concerns."
    assert vet_revision(revision, verdict, [Concern(kind, ["a"])], Settings()) == revision


def test_calculation_error_has_no_unverifiable_arithmetic_revision():
    assert CT.calculation_error not in REVISABLE
    assert vet_revision(
        "Alex missed three visits.",
        Verdict.partially_supported,
        [Concern(CT.calculation_error, ["a"])],
        Settings(),
    ) is None


def test_meaning_shift_replaces_generic_contradiction_in_decision_table():
    key = "c0.1:e1"
    item = JudgedEvidence(
        key=key, linked=ev(), obs=ItemObs(key=key, relation="contradicts")
    )
    decision = decide(
        claim("Physiotherapy was ordered."),
        [item],
        Signals(flags=[FlagObs(type="meaning_shift", keys=[key], conf="high")]),
        Settings(),
    )
    assert decision.verdict == Verdict.contradicted
    assert [c.type for c in decision.concerns] == [CT.meaning_shift]
