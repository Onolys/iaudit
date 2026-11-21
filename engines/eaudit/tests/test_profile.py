"""Optional request `profile` (contract 0.0.2): suppress filter + context_note (SP03 T3)."""

import copy

import pytest
from atomize_helpers import ROSTER, raw
from check_helpers import adhd_prep, claim, ev, link
from onolys_core.llm import StubClient
from pydantic import ValidationError

from eaudit import contract
from eaudit.atomize import atomize_section
from eaudit.atomize.models import AtomizerOutput
from eaudit.atomize.prompt import render_user
from eaudit.check import check_claims, check_one
from eaudit.check.models import VerifierOutput
from eaudit.models import AuditRequest, ConcernType, Section, Verdict

PREP = adhd_prep(roles=True)
TF = frozenset({ConcernType.timeframe_mismatch})
KEY = "c0.1:e1"


def verifier(make_ctx, output: dict):
    stub = StubClient()
    stub.register("check", lambda req: VerifierOutput.model_validate(output))
    return make_ctx(llm=stub)


def out(*flags, **item):
    return {
        "items": [{"key": KEY, "relation": "entails", "conf": "high", **item}],
        "flags": [{"type": t, "keys": [KEY], "conf": "high"} for t in flags],
    }


async def run(make_ctx, output, suppress=frozenset(), **claim_kw):
    c = claim("Alex forgets.", **claim_kw)
    ctx = verifier(make_ctx, output)
    d = await check_one(c, link(ev(turn=3)), PREP, PREP.turns, ctx, suppress=suppress)
    return d, [x.type for x in d.concerns]


# --- suppress filter: verdicts are recomputed ------------------------------------------------


async def test_unsuppressed_timeframe_flag_is_reported(make_ctx):
    d, types = await run(make_ctx, out("timeframe_mismatch"))
    assert d.verdict == Verdict.insufficient_evidence
    assert types == [ConcernType.timeframe_mismatch]


async def test_suppressed_timeframe_mismatch_disappears(make_ctx):
    d, types = await run(make_ctx, out("timeframe_mismatch"), TF)
    assert ConcernType.timeframe_mismatch not in types


async def test_claim_whose_only_flag_was_suppressed_gets_the_no_flag_verdict(make_ctx):
    d, types = await run(make_ctx, out("timeframe_mismatch"), TF)
    baseline, base_types = await run(make_ctx, out())
    assert (d.verdict, types) == (baseline.verdict, base_types) == (Verdict.supported, [])
    assert [e.role.value for e in d.evidence] == ["supporting"]


async def test_item_level_timeframe_observation_is_suppressed_too(make_ctx):
    # no flag at all: the item's own timeframe disagrees with an explicit claim timeframe
    o = out(timeframe="past")
    d, types = await run(make_ctx, o, timeframe_explicit=True)
    assert d.verdict == Verdict.insufficient_evidence and types == [ConcernType.timeframe_mismatch]
    d, types = await run(make_ctx, o, TF, timeframe_explicit=True)
    assert (d.verdict, types) == (Verdict.supported, [])


async def test_one_suppressed_and_one_kept_flag_keeps_the_kept_verdict(make_ctx):
    both = out("timeframe_mismatch", "context_stripping")
    kept_only = out("context_stripping")
    d, types = await run(make_ctx, both, TF)
    k, ktypes = await run(make_ctx, kept_only)
    assert (d.verdict, types) == (k.verdict, ktypes)
    assert d.verdict == Verdict.partially_supported and types == [ConcernType.context_stripping]
    # and without suppression the timeframe flag would have dominated
    u, utypes = await run(make_ctx, both)
    assert (
        u.verdict == Verdict.insufficient_evidence and ConcernType.context_stripping not in utypes
    )


@pytest.mark.parametrize(
    "flag,ctype",
    [
        ("certainty_inflation", ConcernType.certainty_inflation),
        ("context_stripping", ConcernType.context_stripping),
        ("correction_ignored", ConcernType.correction_ignored),
        ("conflicting_accounts_flattened", ConcernType.conflicting_accounts_flattened),
        ("unsupported_causal_link", ConcernType.unsupported_causal_link),
        ("element_gap", ConcernType.unsupported_claim),
        ("quantity_mismatch", ConcernType.quantity_mismatch),
        ("opinion_as_fact", ConcernType.opinion_as_fact),
        ("calculation_error", ConcernType.calculation_error),
        ("meaning_shift", ConcernType.meaning_shift),
        ("unsupported_inference", ConcernType.unsupported_inference),
    ],
)
async def test_every_verifier_flag_type_is_filtered(make_ctx, flag, ctype):
    if flag == "certainty_inflation":  # derived from item certainty, not a verifier flag type
        o, kw = out(certainty="hedged_strong"), {"hedged": False}
    else:
        o, kw = out(flag), {"hedged": False}
    d, types = await run(make_ctx, o, frozenset({ctype}), **kw)
    assert ctype not in types
    assert (d.verdict, types) == (Verdict.supported, [])


async def test_empty_suppress_set_changes_nothing(make_ctx):
    a, ta = await run(make_ctx, out("timeframe_mismatch"))
    b, tb = await run(make_ctx, out("timeframe_mismatch"), frozenset())
    assert (a.verdict, ta) == (b.verdict, tb)


async def test_check_claims_passes_suppress_through(make_ctx):
    c = claim("Alex forgets.")
    ctx = verifier(make_ctx, out("timeframe_mismatch"))
    (d,) = await check_claims([c], [link(ev(turn=3))], PREP, PREP.turns, ctx, suppress=TF)
    assert d.verdict == Verdict.supported and d.concerns == []


# --- request model + contract ------------------------------------------------------------------


def test_request_example_is_0_0_2(example_request):
    assert example_request["schema_version"] == "0.0.2" == contract.SCHEMA_VERSION
    assert "profile" not in example_request
    assert contract.validate_request(example_request) == []
    assert AuditRequest.model_validate(example_request).profile is None


@pytest.mark.parametrize(
    "profile",
    [
        {},
        {"suppress_concerns": []},
        {"suppress_concerns": ["timeframe_mismatch", "opinion_as_fact"]},
        {"context_note": "First person is the interviewer."},
        {"suppress_concerns": ["timeframe_mismatch"], "context_note": "x"},
    ],
)
def test_profile_validates_in_schema_and_model(example_request, profile):
    example_request["profile"] = profile
    assert contract.validate_request(example_request) == []
    assert AuditRequest.model_validate(example_request).profile is not None


@pytest.mark.parametrize(
    "profile",
    [
        {"suppress_concerns": ["nope"]},
        {"suppress_concerns": "timeframe_mismatch"},
        {"context_note": 5},
        {"extra": 1},
    ],
)
def test_bad_profile_is_rejected_by_schema_and_model(example_request, profile):
    example_request["profile"] = profile
    assert contract.validate_request(example_request) != []
    with pytest.raises(ValidationError):
        AuditRequest.model_validate(example_request)


def test_null_profile_is_rejected_by_schema(example_request):
    example_request["profile"] = None
    assert contract.validate_request(example_request) != []


def test_old_schema_version_is_rejected(example_request):
    example_request["schema_version"] = "0.0.1"
    assert contract.validate_request(example_request) != []


def test_profile_examples_validate():
    import json

    ex = contract.default_contracts_dir() / "examples"
    req = json.loads((ex / "profile.request.json").read_text())
    resp = json.loads((ex / "profile.response.json").read_text())
    assert contract.validate_request(req) == []
    assert req["profile"]["suppress_concerns"] and req["profile"]["context_note"]
    assert contract.validate_response(resp) == []
    assert AuditRequest.model_validate(req).profile.suppress_concerns


# --- context_note ------------------------------------------------------------------------------


def test_render_user_without_note_is_byte_identical():
    base = render_user("Alex forgets.", ROSTER)
    assert render_user("Alex forgets.", ROSTER, None) == base
    assert render_user("Alex forgets.", ROSTER, context_note=None) == base
    roster = '[{"speaker": "clinician1", "role": "interviewer"}, {"speaker": "alex1", "role": "respondent"}]'
    assert base == f"Roster: {roster}\n\nSection text:\n<<<\nAlex forgets.\n>>>"


def test_render_user_appends_note_only_when_present():
    base = render_user("Alex forgets.", ROSTER)
    noted = render_user("Alex forgets.", ROSTER, "I means the interviewer.")
    assert noted.startswith(base) and "I means the interviewer." in noted[len(base) :]
    assert render_user("Alex forgets.", ROSTER, "") == base


async def _atomize_user(make_ctx, **kw) -> str:
    seen: list = []
    c = StubClient()

    def fn(req):
        seen.append(req)
        return AtomizerOutput.model_validate({"claims": [raw()], "links": []})

    c.register("atomize", fn)
    ctx = make_ctx(llm=c)
    await atomize_section(Section(id="s", text="Alex forgets things."), ROSTER, ctx, index=0, **kw)
    (req,) = seen
    return req.user, req.cache_prefix


async def test_atomize_prompt_carries_note_but_prefix_and_profileless_user_are_unchanged(make_ctx):
    plain_user, plain_prefix = await _atomize_user(make_ctx)
    assert plain_user == render_user("Alex forgets things.", ROSTER)
    noted_user, noted_prefix = await _atomize_user(make_ctx, context_note="Self-rating note.")
    assert "Self-rating note." in noted_user and noted_user.startswith(plain_user)
    assert noted_prefix == plain_prefix  # cache prefix never depends on the profile


def test_model_copy_roundtrip_keeps_profile(example_request):
    r = copy.deepcopy(example_request)
    r["profile"] = {"suppress_concerns": ["timeframe_mismatch"]}
    m = AuditRequest.model_validate(r)
    assert [c.value for c in m.profile.suppress_concerns] == ["timeframe_mismatch"]
    assert m.profile.context_note is None
