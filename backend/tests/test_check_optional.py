"""05 optional: rate-ratio conflicting accounts, at-least cue refinements, confidence calibration."""

import pytest
from check_helpers import adhd_prep, claim, ev, link

from iaudit_backend.check.amounts import has_at_least_cue
from iaudit_backend.check.group_a import run_group_a
from iaudit_backend.check.models import VerifierOutput
from iaudit_backend.check.synth import decide, judge
from iaudit_backend.check.verifier import apply_floors
from iaudit_backend.config import Settings
from iaudit_backend.models import ConcernType, Verdict

PREP = adhd_prep(roles=True)
TWO_ACCOUNTS = [
    {"source": "self", "speaker": "alex1"},
    {"source": "informant", "speaker": "sam1"},
]


def q(raw, rate, basis="numeric"):
    return {"raw": raw, "rate_per_week": rate, "basis": basis}


def obs(key, **kw):
    return {"key": key, "relation": "entails", "conf": "high", **kw}


def run(c, lk, out, cfg=None):
    cfg = cfg or Settings()
    v = VerifierOutput.model_validate(out)
    items, sig = judge(c, lk, run_group_a(c, lk, PREP.turns), PREP.turns, v, None, cfg)
    return items, sig, decide(c, items, sig, cfg)


def v6(rate_a=0.46, rate_b=0.23, reported_by=TWO_ACCOUNTS, turns=(19, 23)):
    c = claim(
        "Both Alex and his partner agree he forgets errands about twice a month.",
        reported_by=reported_by,
        quantities=[
            {
                "kind": "frequency",
                "raw": "twice a month",
                "bucket": "sometimes",
                "rate_per_week": 0.46,
            }
        ],
    )
    lk = link(ev(n=1, turn=turns[0], role="supporting"), ev(n=2, turn=turns[1], role="supporting"))
    out = {
        "items": [
            obs("c0.1:e1", frequency=[q("twice a month", rate_a)]),
            obs("c0.1:e2", frequency=[q("once a month", rate_b)]),
        ]
    }
    return c, lk, out


# -- rate ratio ------------------------------------------------------------------------------


def test_rate_ratio_fires_conflicting_accounts_without_a_verifier_flag():
    _, sig, dec = run(*v6())
    assert [f.type for f in sig.flags] == ["conflicting_accounts_flattened"]
    assert dec.verdict == Verdict.partially_supported
    assert [c.type for c in dec.concerns] == [ConcernType.conflicting_accounts_flattened]
    assert sig.counts["ratio_conflicts"] == 1


def test_rate_ratio_below_threshold_does_not_fire():
    _, sig, _ = run(*v6(0.46, 0.40))
    assert sig.flags == []


def test_threshold_comes_from_settings():
    c, lk, out = v6(0.46, 0.40)  # ratio 1.15
    _, sig, _ = run(c, lk, out, Settings(check_rate_ratio=1.1))
    assert [f.type for f in sig.flags] == ["conflicting_accounts_flattened"]


def test_rate_ratio_needs_two_reported_accounts():
    _, sig, _ = run(*v6(reported_by=TWO_ACCOUNTS[:1]))
    assert sig.flags == []


def test_rate_ratio_needs_different_speakers():
    _, sig, _ = run(*v6(turns=(19, 19)))  # both items come from Sam
    assert sig.flags == []


def test_rate_ratio_not_added_twice_when_the_verifier_already_flagged_it():
    c, lk, out = v6()
    out["flags"] = [{"type": "conflicting_accounts_flattened", "keys": ["c0.1:e1"], "conf": "high"}]
    _, sig, _ = run(c, lk, out)
    assert [f.type for f in sig.flags] == ["conflicting_accounts_flattened"]


def test_rate_ratio_ignores_zero_and_missing_rates():
    _, sig, _ = run(*v6(0.46, 0))
    assert sig.flags == []


# -- at-least cues ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "raw",
    ["at least twice a week", "more than ten times", "a number of times", "numerous occasions",
     "a lot", "again and again", "over and over", "frequently"],
)  # fmt: skip
def test_new_lower_bound_cues(raw):
    assert has_at_least_cue(raw)


@pytest.mark.parametrize(
    "raw",
    ["some difficulty", "mild", "a little", "not often", "hardly ever often", "never frequently",
     "rarely, if often at all"],
)  # fmt: skip
def test_level_words_and_negated_cues_are_not_at_least(raw):
    assert not has_at_least_cue(raw)


# -- calibration -----------------------------------------------------------------------------


def test_defaults_keep_the_fixed_mapping():
    s = Settings()
    assert s.check_conf_values == {"low": 0.3, "medium": 0.6, "high": 0.9}


def test_calibrated_values_move_the_floors():
    out = VerifierOutput.model_validate(
        {
            "items": [obs("c0.1:e1", conf="low")],
            "flags": [{"type": "context_stripping", "keys": ["c0.1:e1"], "conf": "medium"}],
        }
    )
    kept, _ = apply_floors(out, Settings())
    assert len(kept.items) == 0 and len(kept.flags) == 1
    kept, counts = apply_floors(out, Settings(check_conf_low=0.55, check_conf_medium=0.55))
    assert len(kept.items) == 1 and kept.flags == [] and counts["flags_below_floor"] == 1


def test_calibration_must_be_ordered():
    with pytest.raises(ValueError):
        Settings(check_conf_low=0.9, check_conf_high=0.3)
