import random

import pytest
from check_helpers import claim, ev

from iaudit_backend.check.models import Concern, FlagObs, ItemObs, JudgedEvidence, Signals
from iaudit_backend.check.synth import decide, dedup
from iaudit_backend.config import Settings
from iaudit_backend.models import ConcernType as CT
from iaudit_backend.models import EvidenceRole as R
from iaudit_backend.models import Verdict as V

CFG = Settings()


def j(n=1, rel="entails", **kw):
    """A judged item. Extra kwargs: obs fields, or JudgedEvidence fields (endorsed, demote...)."""
    jf = {k: kw.pop(k) for k in ("endorsed", "demote", "attribution", "cited") if k in kw}
    obs = (
        None
        if rel is None
        else ItemObs.model_validate({"key": f"c0.1:e{n}", "relation": rel, **kw})
    )
    return JudgedEvidence(key=f"c0.1:e{n}", linked=ev(n=n), obs=obs, **jf)


def sig(*flags, failed=False):
    return Signals(
        flags=[FlagObs(type=t, keys=k, conf="high") for t, k in flags], failed_inference=failed
    )


def run(items, *flags, c=None, **kw):
    return decide(c or claim("Alex forgets."), items, sig(*flags, **kw), CFG)


def types(d):
    return [c.type for c in d.concerns]


def guard(c, d):
    roles = list(d.roles.values())
    sup, con = roles.count(R.supporting), roles.count(R.contradicting)
    assert (d.verdict == V.supported) == (sup >= 1 and con == 0 and not d.concerns)
    if d.verdict == V.contradicted:
        assert con >= 1
    if d.verdict == V.partially_supported:
        assert d.concerns
    if d.verdict == V.insufficient_evidence:
        assert con == 0
    if d.verdict == V.out_of_scope:
        assert not d.concerns and not d.roles
    for cn in d.concerns:
        assert all(k in d.roles for k in cn.keys)
    assert len({cn.type for cn in d.concerns}) == len(d.concerns)


def test_d0_out_of_scope():
    c = claim("It is ADHD.", scope="out_of_scope", oos_category="diagnostic_conclusion")
    d = run([], c=c)
    assert (d.row, d.verdict, d.concerns, d.roles) == ("D0", V.out_of_scope, [], {})


def test_d2_no_evidence():
    d = run([])
    assert (d.row, d.verdict, types(d)) == ("D2", V.insufficient_evidence, [CT.unsupported_claim])


def test_d4_negation_reversal_suppresses_generic_contradiction():  # V2
    d = run([j(rel="contradicts", polarity="negated")])
    assert (d.row, d.verdict, types(d)) == ("D4", V.contradicted, [CT.negation_reversal])
    assert d.roles == {"c0.1:e1": R.contradicting}


def test_d4_wrong_attribution_beats_negation_reversal():  # V3
    d = run([j(rel="contradicts", polarity="negated", experiencer="other_person")])
    assert (d.row, d.verdict, types(d)) == ("D4", V.contradicted, [CT.wrong_attribution])


def test_d4_generic_when_nothing_more_specific():
    d = run([j(rel="contradicts", polarity="affirmed")])
    assert (d.verdict, types(d)) == (V.contradicted, [CT.contradictory_evidence])


def test_d4_amount_gap_escalates_to_contradiction_and_relabels_item():
    c = claim("Alex naps.", quantities=["constantly"])
    obs = {"frequency": [{"raw": "rarely", "basis": "relative"}]}
    d = run([j(**obs)], c=c)
    assert (d.row, d.verdict, types(d)) == ("D4", V.contradicted, [CT.frequency_severity_inflation])
    assert d.roles == {"c0.1:e1": R.contradicting}
    assert d.concerns[0].direction == "inflates"


def test_zero_bucket_escalates():
    c = claim("Alex naps.", quantities=["sometimes"])
    d = run([j(frequency=[{"raw": "never", "basis": "relative"}])], c=c)
    assert d.verdict == V.contradicted and d.roles["c0.1:e1"] == R.contradicting


def test_d5_mixed_support_and_contradiction_is_partial():
    d = run([j(1), j(2, rel="contradicts", polarity="affirmed")])
    assert (d.row, d.verdict, types(d)) == (
        "D5",
        V.partially_supported,
        [CT.contradictory_evidence],
    )
    assert d.roles == {"c0.1:e1": R.supporting, "c0.1:e2": R.contradicting}


def test_d5_conflicting_accounts_replaces_generic_contradiction():
    d = run(
        [j(1), j(2, rel="contradicts", polarity="affirmed")],
        ("conflicting_accounts_flattened", ["c0.1:e1", "c0.1:e2"]),
    )
    assert types(d) == [CT.conflicting_accounts_flattened]


def test_d6_timeframe_demotion_leaves_no_support():  # V5
    d = run([j(timeframe="childhood", demote="timeframe")])
    assert (d.row, d.verdict, types(d)) == ("D6", V.insufficient_evidence, [CT.timeframe_mismatch])
    assert d.roles == {"c0.1:e1": R.qualifying}


def test_d6_failed_inference_is_unsupported_claim():
    d = run([j(1, demote="inference"), j(2, demote="inference")], failed=True)
    assert (d.row, d.verdict, types(d)) == ("D6", V.insufficient_evidence, [CT.unsupported_claim])
    assert set(d.roles.values()) == {R.qualifying}


def test_d6_reporter_mismatch_is_wrong_attribution_and_never_support():
    d = run([j(attribution="mismatch")])
    assert (d.verdict, types(d)) == (V.insufficient_evidence, [CT.wrong_attribution])
    assert d.roles == {"c0.1:e1": R.qualifying}


def test_mismatched_contradiction_is_qualifying_not_contradicting():
    d = run([j(rel="contradicts", attribution="mismatch")])
    assert d.verdict == V.insufficient_evidence and d.roles == {"c0.1:e1": R.qualifying}


def test_d7_nothing_relevant():
    d = run([j(rel="not_addresses"), j(2, rel=None)])
    assert (d.row, d.verdict, types(d), d.roles) == (
        "D7",
        V.insufficient_evidence,
        [CT.unsupported_claim],
        {},
    )
    assert d.counts["items_dropped"] == 2


def test_non_endorsed_items_are_qualifying_and_unsupportive():
    d = run([j(endorsed=False)])
    assert d.verdict == V.insufficient_evidence and d.roles == {"c0.1:e1": R.qualifying}


def test_d8_each_supported_concern_gives_partial():
    for flag, ctype in [
        ("context_stripping", CT.context_stripping),
        ("correction_ignored", CT.correction_ignored),
        ("conflicting_accounts_flattened", CT.conflicting_accounts_flattened),
        ("unsupported_causal_link", CT.unsupported_causal_link),
        ("element_gap", CT.unsupported_claim),
        ("certainty_inflation", CT.certainty_inflation),
    ]:
        d = run([j(cited=flag != "element_gap")], (flag, ["c0.1:e1"]))
        assert (d.row, d.verdict, types(d)) == ("D8", V.partially_supported, [ctype]), flag
        assert d.roles == {"c0.1:e1": R.supporting}


def test_d8_cited_item_judged_not_addresses_still_counts_as_partial_support():
    d = run([j(rel="not_addresses", cited=True)], ("unsupported_causal_link", ["c0.1:e1"]))
    assert (d.verdict, d.roles) == (V.partially_supported, {"c0.1:e1": R.supporting})


def test_d8_certainty_from_strong_hedge_in_item():
    d = run([j(certainty="hedged_strong", conf="high")])
    assert (d.verdict, types(d)) == (V.partially_supported, [CT.certainty_inflation])


def test_d8_inflation_and_understatement_texts():
    c = claim("Alex naps.", quantities=["constantly"])
    d = run([j(frequency=[{"raw": "most days", "basis": "relative"}])], c=c)
    assert (d.row, d.verdict) == ("D8", V.partially_supported)
    assert d.concerns[0].direction == "inflates" and d.concerns[0].scale == "frequency"
    c = claim("Alex struggles.", quantities=[{"kind": "severity", "raw": "mild"}])
    d = run([j(severity=[{"raw": "severe", "basis": "relative"}])], c=c)
    assert (d.verdict, d.concerns[0].direction) == (V.partially_supported, "understates")
    assert d.roles == {"c0.1:e1": R.supporting}


def test_conflicting_accounts_suppresses_amount_compare():
    c = claim("Alex naps.", quantities=["constantly"])
    d = run(
        [j(frequency=[{"raw": "rarely", "basis": "relative"}])],
        ("conflicting_accounts_flattened", ["c0.1:e1"]),
        c=c,
    )
    assert types(d) == [CT.conflicting_accounts_flattened] and d.verdict == V.partially_supported


def test_d9_supported_when_nothing_flagged():
    d = run([j(1), j(2, rel="not_addresses")])
    assert (d.row, d.verdict, d.concerns, d.roles) == (
        "D9",
        V.supported,
        [],
        {"c0.1:e1": R.supporting},
    )


def test_other_person_entailment_is_wrong_attribution_not_support():
    d = run([j(experiencer="other_person")])
    assert (d.verdict, types(d), d.roles) == (
        V.insufficient_evidence,
        [CT.wrong_attribution],
        {"c0.1:e1": R.qualifying},
    )
    d = run([j(1), j(2, experiencer="other_person")])
    assert (d.verdict, types(d)) == (V.partially_supported, [CT.wrong_attribution])


def test_dedup_same_direction_unions_keys_and_scales():
    out = dedup(
        [
            Concern(CT.frequency_severity_inflation, ["a"], "inflates", "severity"),
            Concern(CT.frequency_severity_inflation, ["b"], "inflates", "frequency"),
        ]
    )
    assert len(out) == 1 and out[0].keys == ["a", "b"] and out[0].direction == "inflates"
    assert out[0].scale == "frequency and severity"


def test_dedup_opposite_directions_report_the_inflating_one_only():
    for order in (("understates", "inflates"), ("inflates", "understates")):
        scale = {"inflates": "frequency", "understates": "severity"}
        out = dedup(
            [
                Concern(
                    CT.frequency_severity_inflation, ["i" if d == "inflates" else "u"], d, scale[d]
                )
                for d in order
            ]
        )
        assert [(c.direction, c.scale, c.keys) for c in out] == [("inflates", "frequency", ["i"])]


def test_mixed_direction_amounts_never_say_inflates_the_severity():
    c = claim(
        "Alex struggles.",
        quantities=[
            {"kind": "frequency", "raw": "always", "bucket": "always"},
            {"kind": "severity", "raw": "mild", "bucket": "mild"},
        ],
    )
    it = j(
        frequency=[{"raw": "often", "basis": "relative"}],
        severity=[{"raw": "severe", "basis": "relative"}],
    )
    (cn,) = run([it], c=c).concerns
    assert (cn.direction, cn.scale) == ("inflates", "frequency")


def test_d5_correction_ignored_replaces_generic_contradiction():
    items = [j(1), j(2, rel="contradicts", polarity="affirmed")]
    d = run(items, ("correction_ignored", ["c0.1:e1"]))
    assert (d.row, types(d)) == ("D5", [CT.correction_ignored])
    d = run(
        items, ("correction_ignored", ["c0.1:e1"]), ("conflicting_accounts_flattened", ["c0.1:e1"])
    )
    assert types(d) == [CT.conflicting_accounts_flattened]


def test_dedup_specific_suppresses_generic_on_same_items_only():
    out = dedup(
        [Concern(CT.negation_reversal, ["a"]), Concern(CT.contradictory_evidence, ["a", "b"])]
    )
    assert [c.type for c in out] == [CT.negation_reversal]
    out = dedup([Concern(CT.negation_reversal, ["a"]), Concern(CT.contradictory_evidence, ["b"])])
    assert len(out) == 2
    out = dedup([Concern(CT.context_stripping, ["a"]), Concern(CT.unsupported_claim)])
    assert [c.type for c in out] == [CT.context_stripping]


def test_independent_aspects_coexist():
    out = dedup(
        [Concern(CT.certainty_inflation, ["a"]), Concern(CT.frequency_severity_inflation, ["a"])]
    )
    assert len(out) == 2


def test_property_decisions_always_satisfy_the_contract_guards():
    rng = random.Random(1234)
    flags = ["timeframe_mismatch", "certainty_inflation", "context_stripping", "correction_ignored",
             "conflicting_accounts_flattened", "unsupported_causal_link", "element_gap"]  # fmt: skip
    quants = [(), ("constantly",), ("rarely",), ("sometimes",), ("every day",)]
    raws = ["never", "rarely", "sometimes", "often", "most days", "constantly", "usually"]
    for _ in range(3000):
        items = []
        for n in range(1, rng.randint(0, 4) + 1):
            rel = rng.choice(["entails", "contradicts", "not_addresses", None])
            kw = dict(
                polarity=rng.choice(["affirmed", "negated", "unclear"]),
                timeframe=rng.choice(["current", "past", "childhood", "unspecified"]),
                certainty=rng.choice(["definite", "hedged_light", "hedged_strong"]),
                experiencer=rng.choice(["claim_subject", "claim_subject", "other_person", "unclear"]),
                conf=rng.choice(["medium", "high"]),
                frequency=[{"raw": rng.choice(raws), "basis": rng.choice(["relative", "numeric"])}]
                if rng.random() < 0.5 else [],
                endorsed=rng.random() < 0.85,
                demote=rng.choice([None, None, None, "timeframe", "inference"]),
                attribution=rng.choice(["ok", "ok", "mismatch", "skip"]),
                cited=rng.random() < 0.2,
            )  # fmt: skip
            items.append(j(n, rel, **kw))
        keys = [it.key for it in items] or ["c0.1:e1"]
        fl = [
            (rng.choice(flags), rng.sample(keys, rng.randint(0, len(keys))))
            for _ in range(rng.randint(0, 3))
        ]
        c = claim(
            "Alex forgets, because of that.", polarity=rng.choice(["affirmed", "negated"]),
            hedged=rng.random() < 0.3, quantities=list(rng.choice(quants)),
        )  # fmt: skip
        d = decide(c, items, sig(*fl), CFG)
        guard(c, d)


# --- quantity_mismatch (mission check 13) ------------------------------------------------------


def test_quantity_flag_with_supported_behaviour_is_d8_partial():
    d = run([j(cited=True)], ("quantity_mismatch", ["c0.1:e1"]))
    assert (d.row, d.verdict, types(d)) == ("D8", V.partially_supported, [CT.quantity_mismatch])
    assert d.roles == {"c0.1:e1": R.supporting}


def test_quantity_flag_on_contradicting_item_is_d4_and_replaces_generic_contradiction():
    d = run([j(rel="contradicts")], ("quantity_mismatch", ["c0.1:e1"]))
    assert (d.row, d.verdict, types(d)) == ("D4", V.contradicted, [CT.quantity_mismatch])
    guard(claim("Alex forgets."), d)


def test_frequency_beats_quantity_on_the_same_key():
    out = dedup(
        [
            Concern(CT.quantity_mismatch, ["c0.1:e1"]),
            Concern(CT.frequency_severity_inflation, ["c0.1:e1"], "inflates", "frequency"),
        ]
    )
    assert [c.type for c in out] == [CT.frequency_severity_inflation]


def test_quantity_beats_contradictory_on_the_same_key_but_not_on_other_keys():
    out = dedup(
        [
            Concern(CT.contradictory_evidence, ["c0.1:e1"]),
            Concern(CT.quantity_mismatch, ["c0.1:e1"]),
        ]
    )
    assert [c.type for c in out] == [CT.quantity_mismatch]
    out = dedup(
        [
            Concern(CT.contradictory_evidence, ["c0.1:e2"]),
            Concern(CT.quantity_mismatch, ["c0.1:e1"]),
        ]
    )
    assert [c.type for c in out] == [CT.contradictory_evidence, CT.quantity_mismatch]


def test_quantity_flag_with_not_addresses_item_keeps_the_concern():
    d = run([j(rel="not_addresses", cited=True)], ("quantity_mismatch", ["c0.1:e1"]))
    assert (d.verdict, types(d), d.roles) == (
        V.partially_supported,
        [CT.quantity_mismatch],
        {"c0.1:e1": R.supporting},
    )


def test_quantity_concern_sorts_last_and_template_has_no_digits_or_banned_words():
    from iaudit_backend.check.templates import BANNED, Slots, concern_text

    d = run([j(cited=True)], ("quantity_mismatch", ["c0.1:e1"]), ("context_stripping", ["c0.1:e1"]))
    assert types(d) == [CT.context_stripping, CT.quantity_mismatch]
    text = concern_text(d.concerns[-1], Slots())
    assert not any(ch.isdigit() for ch in text) and not BANNED.search(text)


_STACK_PARTNERS = [
    CT.certainty_inflation,
    CT.correction_ignored,
    CT.conflicting_accounts_flattened,
    CT.timeframe_mismatch,
]


@pytest.mark.parametrize("other", _STACK_PARTNERS)
def test_dedup_quantity_mismatch_yields_to_overlapping_partner(other):
    got = dedup([Concern(CT.quantity_mismatch, ["a"]), Concern(other, ["a", "b"])])
    assert [c.type for c in got] == [other]


@pytest.mark.parametrize("other", _STACK_PARTNERS)
def test_dedup_quantity_mismatch_yields_when_either_side_has_no_keys(other):
    assert [c.type for c in dedup([Concern(CT.quantity_mismatch, []), Concern(other, ["b"])])] == [
        other
    ]
    assert [c.type for c in dedup([Concern(CT.quantity_mismatch, ["a"]), Concern(other, [])])] == [
        other
    ]


@pytest.mark.parametrize("other", _STACK_PARTNERS)
def test_dedup_quantity_mismatch_kept_on_different_items(other):
    got = dedup([Concern(CT.quantity_mismatch, ["a"]), Concern(other, ["b"])])
    assert {c.type for c in got} == {CT.quantity_mismatch, other}
