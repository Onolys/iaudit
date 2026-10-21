from check_helpers import adhd_prep, claim, ev, link

from iaudit_backend.check.group_a import run_group_a
from iaudit_backend.check.models import VerifierOutput
from iaudit_backend.check.synth import (
    certainty_keys,
    flag_concerns,
    has_causal_cue,
    judge,
)
from iaudit_backend.models import ConcernType

PREP = adhd_prep(roles=True)


def item(key="c0.1:e1", rel="entails", **kw):
    return {"key": key, "relation": rel, **kw}


def run(c, lk, out):
    v = VerifierOutput.model_validate(out)
    return judge(c, lk, run_group_a(c, lk, PREP.turns), PREP.turns, v)


def test_certainty_fires_for_unhedged_claim_against_strong_hedge_only():
    lk = link(ev(n=1), ev(n=2, turn=5), ev(n=3, turn=7))
    out = {
        "items": [
            item("c0.1:e1", certainty="hedged_strong", conf="medium"),
            item("c0.1:e2", certainty="hedged_light", conf="high"),
            item("c0.1:e3", certainty="definite", conf="high"),
        ]
    }
    items, sig = run(claim("x"), lk, out)
    assert certainty_keys(claim("x"), items, sig.flags, 0.6) == ["c0.1:e1"]
    assert certainty_keys(claim("x", hedged=True), items, sig.flags, 0.6) == []
    assert certainty_keys(claim("x"), items, sig.flags, 0.7) == []  # below the P1 floor


def test_certainty_flag_counts_too():
    items, sig = run(
        claim("x"),
        link(ev()),
        {"items": [item()], "flags": [{"type": "certainty_inflation", "keys": ["c0.1:e1"]}]},
    )
    assert certainty_keys(claim("x"), items, sig.flags, 0.6) == ["c0.1:e1"]


def test_causal_cue_gate_ignores_flag_without_cue():
    assert has_causal_cue(claim("His distractibility caused a bad review."))
    assert has_causal_cue(claim("It happened because of that."))
    assert not has_causal_cue(claim("He forgets his keys."))
    flag = {"type": "unsupported_causal_link", "keys": ["c0.1:e1"], "conf": "high"}
    _, sig = run(claim("He forgets his keys."), link(ev()), {"items": [item()], "flags": [flag]})
    assert sig.flags == [] and sig.counts["flags_suppressed"] == 1
    _, sig = run(
        claim("It was caused by stress."), link(ev()), {"items": [item()], "flags": [flag]}
    )
    assert len(sig.flags) == 1


def test_flag_cited_items_are_marked_and_unknown_keys_dropped():
    flag = {"type": "context_stripping", "keys": ["c0.1:e1", "zzz"], "conf": "high"}
    items, sig = run(claim("x"), link(ev()), {"items": [item()], "flags": [flag]})
    assert items[0].cited and sig.flags[0].keys == ["c0.1:e1"]
    cs = flag_concerns(items, sig.flags)
    assert [(c.type, c.keys) for c in cs] == [(ConcernType.context_stripping, ["c0.1:e1"])]


def test_flag_without_keys_rests_on_the_items_the_claim_leans_on():
    items, sig = run(
        claim("x"),
        link(ev(n=1), ev(n=2, turn=5)),
        {
            "items": [item("c0.1:e1"), item("c0.1:e2", "not_addresses")],
            "flags": [{"type": "element_gap"}],
        },
    )
    (c,) = flag_concerns(items, sig.flags)
    assert (c.type, c.keys) == (ConcernType.unsupported_claim, ["c0.1:e1"])


def inference_link():
    return link(
        ev(n=1, role="supporting"), ev(n=2, turn=5),
        ev(n=3, lt="inference", premises=["c0.1:e1", "c0.1:e2"], step="Both."),
    )  # fmt: skip


def test_inference_supported_when_all_premises_entail_and_step_acceptable():
    out = {
        "items": [item("c0.1:e1"), item("c0.1:e2")],
        "inferences": [{"key": "c0.1:e3", "step_acceptable": True, "conf": "high"}],
    }
    items, sig = run(claim("x"), inference_link(), out)
    assert not sig.failed_inference and [it.demote for it in items] == [None, None]


def test_inference_fails_on_a_non_entailing_premise_or_bad_step():
    inf = [{"key": "c0.1:e3", "step_acceptable": True, "conf": "high"}]
    items, sig = run(
        claim("x"),
        inference_link(),
        {"items": [item("c0.1:e1"), item("c0.1:e2", "not_addresses")], "inferences": inf},
    )
    assert sig.failed_inference and [it.demote for it in items] == ["inference", "inference"]
    bad = [{"key": "c0.1:e3", "step_acceptable": False, "conf": "high"}]
    items, sig = run(
        claim("x"),
        inference_link(),
        {"items": [item("c0.1:e1"), item("c0.1:e2")], "inferences": bad},
    )
    assert sig.failed_inference and all(it.demote == "inference" for it in items)


def test_inference_judgment_below_floor_counts_as_failed():
    # apply_floors drops low-confidence inferences, so the group has no judgment
    items, sig = run(claim("x"), inference_link(), {"items": [item("c0.1:e1"), item("c0.1:e2")]})
    assert sig.failed_inference


def test_inference_item_itself_is_not_a_judged_item():
    items, _ = run(claim("x"), inference_link(), {"items": [item("c0.1:e1"), item("c0.1:e2")]})
    assert [it.key for it in items] == ["c0.1:e1", "c0.1:e2"]


def _qflag(keys=("c0.1:e1",)):
    return {"type": "quantity_mismatch", "keys": list(keys), "conf": "high"}


# PREP turn 3 gives figures ("three or four times"); turn 5 gives none.
def test_quantity_flag_needs_a_number_in_claim_and_in_a_cited_turn():
    out = {"items": [item()], "flags": [_qflag()]}
    items, sig = run(claim("The team had 12 people."), link(ev(turn=3)), out)
    assert [f.type for f in sig.flags] == ["quantity_mismatch"] and items[0].cited
    assert "flags_suppressed" not in sig.counts
    # claim without a number token: suppressed and counted
    _, sig = run(claim("The team was large."), link(ev(turn=3)), out)
    assert sig.flags == [] and sig.counts["flags_suppressed"] == 1
    # cited turn without a number token: suppressed and counted
    _, sig = run(claim("The team had 12 people."), link(ev(turn=5)), out)
    assert sig.flags == [] and sig.counts["flags_suppressed"] == 1


def test_quantity_flag_guard_reads_only_cited_items_turns():
    lk = link(ev(n=1, turn=5), ev(n=2, turn=3))
    out = {"items": [item("c0.1:e1"), item("c0.1:e2")], "flags": [_qflag(["c0.1:e1"])]}
    _, sig = run(claim("The team had 12 people."), lk, out)
    assert sig.flags == [] and sig.counts["flags_suppressed"] == 1
    out["flags"] = [_qflag(["c0.1:e2"])]
    _, sig = run(claim("The team had 12 people."), lk, out)
    assert len(sig.flags) == 1


def test_quantity_flag_is_subject_to_the_p1_floor():
    from iaudit_backend.check.models import VerifierOutput
    from iaudit_backend.check.verifier import apply_floors
    from iaudit_backend.config import Settings

    v = VerifierOutput.model_validate({"items": [item()], "flags": [{**_qflag(), "conf": "low"}]})
    out, counts = apply_floors(v, Settings())
    assert out.flags == [] and counts["flags_below_floor"] == 1
