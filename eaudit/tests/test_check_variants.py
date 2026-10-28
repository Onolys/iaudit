"""Acceptance 1: a stub verifier returning the Variant-map observations (no network)."""

import json

from atomize_helpers import FIXTURES
from check_helpers import adhd_prep, claim, ev, link

from eaudit.atomize.models import AtomicClaim, AtomizerOutput
from eaudit.check import check_claims
from eaudit.check.models import VerifierOutput
from eaudit.llm import StubClient

PREP = adhd_prep(roles=True)
TURNS = PREP.turns
UNSPEC = [{"source": "unspecified", "speaker": None}]


def q(raw, rate=None, bucket=None, basis="relative"):
    return {"raw": raw, "rate_per_week": rate, "bucket_guess": bucket, "basis": basis}


def obs(key, rel="entails", **kw):
    return {"key": key, "relation": rel, "conf": "high", **kw}


def run_stub(make_ctx, by_claim: dict[str, dict]):
    stub = StubClient()
    calls: list[str] = []

    def fn(req):
        cid = req.fixture_key.split(".check.")[1]
        calls.append(cid)
        return VerifierOutput.model_validate(by_claim[cid])

    stub.register("check", fn)
    return make_ctx(llm=stub), calls


def faithful_claims() -> list[AtomicClaim]:
    raw = json.loads((FIXTURES / "adhd-faithful.atomize.s0.json").read_text())
    out = AtomizerOutput.model_validate(raw)
    return [
        AtomicClaim.model_validate(
            {**c.model_dump(exclude={"ref"}), "id": f"c0.{n}", "section_index": 0}
        )
        for n, c in enumerate(out.claims, 1)
    ]


# claim letter order a..k -> (turn, observation fields)
FAITHFUL = [
    (3, dict(frequency=[q("Most meetings"), q("three or four times a week", 3.5, basis="numeric")])),
    (7, dict(certainty="hedged_light", frequency=[q("constantly"), q("every day", 7.0, basis="numeric")])),
    (9, {}),
    (11, {}),
    (11, {}),
    (19, dict(frequency=[q("twice a month", 0.46, basis="numeric")])),
    (23, dict(frequency=[q("once a month", 0.23, basis="numeric")])),
    (15, dict(timeframe="childhood", frequency=[q("constantly")])),
    (15, dict(timeframe="childhood")),
    (25, dict(timeframe="past")),
    (5, dict(polarity="negated")),
]  # fmt: skip


async def test_faithful_claims_are_all_supported_with_no_concerns(make_ctx):
    claims = faithful_claims()
    links, outputs = [], {}
    for c, (turn, fields) in zip(claims, FAITHFUL, strict=True):
        links.append(link(ev(cid=c.id, turn=turn), cid=c.id))
        outputs[c.id] = {"items": [obs(f"{c.id}:e1", **fields)]}
    ctx, calls = run_stub(make_ctx, outputs)
    drafts = await check_claims(claims, links, PREP, TURNS, ctx)
    assert len(calls) == 11
    for d in drafts:
        assert (d.verdict, d.concerns, d.outcome) == ("supported", [], "ok"), d.key
        assert [e.role for e in d.evidence] == ["supporting"], d.key


async def run_variant(make_ctx, c, lk, output):
    ctx, calls = run_stub(make_ctx, {c.id: output})
    (d,) = await check_claims([c], [lk], PREP, TURNS, ctx)
    return d, calls


def types(d):
    return [x.type.value for x in d.concerns]


def roles(d):
    return {e.key: e.role.value for e in d.evidence}


async def test_v1_inflation(make_ctx):
    c = claim(
        "Alex loses attention in every meeting, several times a day.",
        reported_by=UNSPEC,
        quantities=[
            {"kind": "frequency", "raw": "every meeting", "bucket": "always"},
            {"kind": "frequency", "raw": "several times a day", "bucket": "always"},
        ],
    )
    out = {
        "items": [
            obs(
                "c0.1:e1",
                frequency=[
                    q("Most meetings"),
                    q("three or four times a week", 3.5, basis="numeric"),
                ],
            )
        ]
    }
    d, _ = await run_variant(make_ctx, c, link(ev(turn=3)), out)
    assert (d.verdict, types(d)) == ("partially_supported", ["frequency_severity_inflation"])
    assert "inflates" in d.explanation and "inflates" in d.concerns[0].explanation
    assert roles(d) == {"c0.1:e1": "supporting"}


async def test_v2_negation_reversal(make_ctx):
    c = claim("He makes frequent careless mistakes in reports.", reported_by=UNSPEC)
    out = {"items": [obs("c0.1:e1", "contradicts", polarity="negated")]}
    d, _ = await run_variant(make_ctx, c, link(ev(turn=5, role="contradicting")), out)
    assert (d.verdict, types(d)) == ("contradicted", ["negation_reversal"])
    assert roles(d) == {"c0.1:e1": "contradicting"}


async def test_v3_wrong_attribution(make_ctx):
    c = claim("He frequently forgets appointments.", reported_by=UNSPEC)
    out = {"items": [obs("c0.1:e1", "contradicts", polarity="negated", experiencer="other_person")]}
    d, _ = await run_variant(make_ctx, c, link(ev(turn=21, role="contradicting")), out)
    assert (d.verdict, types(d)) == ("contradicted", ["wrong_attribution"])
    assert roles(d) == {"c0.1:e1": "contradicting"}


async def test_v4_question_as_answer_makes_zero_calls(make_ctx):
    c = claim("He is easily distracted by his surroundings.", reported_by=UNSPEC)
    lk = link(ev(turns=[12, 13], role="qualifying", status="non_answer"))
    d, calls = await run_variant(make_ctx, c, lk, {"items": []})
    assert (d.verdict, types(d), calls) == ("insufficient_evidence", ["question_as_answer"], [])
    assert roles(d) == {"c0.1:e1": "qualifying"}


async def test_v5_timeframe_mismatch(make_ctx):
    c = claim(
        "He currently forgets work assignments weekly.", reported_by=UNSPEC, timeframe_explicit=True
    )
    out = {
        "items": [
            obs(
                "c0.1:e1",
                timeframe="childhood",
                conf="medium",
                frequency=[q("once a week", 1.0, basis="numeric")],
            )
        ]
    }
    d, _ = await run_variant(make_ctx, c, link(ev(turn=17, role="qualifying")), out)
    assert (d.verdict, types(d)) == ("insufficient_evidence", ["timeframe_mismatch"])
    assert roles(d) == {"c0.1:e1": "qualifying"}


async def test_v6_conflicting_accounts_via_verifier_flag(make_ctx):
    c = claim(
        "Both Alex and his partner agree he forgets errands about twice a month.",
        reported_by=[
            {"source": "self", "speaker": "alex1"},
            {"source": "informant", "speaker": "sam1"},
        ],
        quantities=[
            {
                "kind": "frequency",
                "raw": "twice a month",
                "bucket": "sometimes",
                "rate_per_week": 0.46,
            }
        ],
    )
    out = {
        "items": [
            obs("c0.1:e1", frequency=[q("twice a month", 0.46, basis="numeric")]),
            obs("c0.1:e2", frequency=[q("once a month", 0.23, basis="numeric")]),
        ],
        "flags": [
            {
                "type": "conflicting_accounts_flattened",
                "keys": ["c0.1:e1", "c0.1:e2"],
                "conf": "high",
            }
        ],
    }
    lk = link(ev(n=1, turn=19), ev(n=2, turn=23, role="qualifying"))
    d, _ = await run_variant(make_ctx, c, lk, out)
    assert (d.verdict, types(d)) == ("partially_supported", ["conflicting_accounts_flattened"])


async def test_v7_context_stripping(make_ctx):
    c = claim("The unfinished bathroom shows his difficulty completing tasks.", reported_by=UNSPEC)
    out = {
        "items": [obs("c0.1:e1")],
        "flags": [{"type": "context_stripping", "keys": ["c0.1:e1"], "conf": "high"}],
    }
    d, _ = await run_variant(make_ctx, c, link(ev(turn=11)), out)
    assert (d.verdict, types(d)) == ("partially_supported", ["context_stripping"])
    assert roles(d) == {"c0.1:e1": "supporting"}


async def test_v8_unsupported_causal_link(make_ctx):
    c = claim(
        "His distractibility caused a negative performance review.",
        reported_by=UNSPEC,
        timeframe="past",
    )
    out = {
        "items": [obs("c0.1:e1")],
        "flags": [{"type": "unsupported_causal_link", "keys": ["c0.1:e1"], "conf": "high"}],
    }
    d, _ = await run_variant(make_ctx, c, link(ev(turn=25, role="qualifying")), out)
    assert (d.verdict, types(d)) == ("partially_supported", ["unsupported_causal_link"])
    assert roles(d) == {"c0.1:e1": "supporting"}


async def test_fictional_mild_vs_severe_understates(make_ctx):
    c = claim(
        "Jordan has mild trouble sleeping.",
        reported_by=UNSPEC,
        quantities=[{"kind": "severity", "raw": "mild", "bucket": "mild"}],
    )
    out = {"items": [obs("c0.1:e1", severity=[q("severe", bucket="severe")])]}
    d, _ = await run_variant(make_ctx, c, link(ev(turn=3)), out)
    assert (d.verdict, types(d)) == ("partially_supported", ["frequency_severity_inflation"])
    assert "understates" in d.explanation and "understates" in d.concerns[0].explanation
    assert d.concerns[0].evidence_keys == ["c0.1:e1"]
