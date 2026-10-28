"""Fictional quantity and taxonomy v2 boundaries with scripted verifier output.

Each pair scripts the verifier output (no LLM, no network) and asserts the exact concern set the
pipeline settles on. The scripted outputs are what a careful verifier returns; the first and
sixth, and the date, "about ten" and previous-medication pairs also carry a stray
`quantity_mismatch` flag to pin the precedence and grounding rules.

The taxonomy v2 pairs contrast a discrepancy with a faithful near-miss on the same
interview. They exercise the checker, gates, deduplication, verdict and evidence roles.
"""

import pytest
from check_helpers import claim, ev, link

from eaudit.check import check_claims
from eaudit.check.models import VerifierOutput
from eaudit.llm import StubClient
from eaudit.models import Turn
from eaudit.prep import PrepResult, index_turns, pair_turns

UNSPEC = [{"source": "unspecified", "speaker": None}]
E1 = "c0.1:e1"
E2 = "c0.1:e2"


def prep_for(*replies: str) -> PrepResult:
    """Alternating question/answer turns; reply i sits at turn 2*i+1."""
    turns = []
    for i, text in enumerate(replies):
        turns.append(Turn(id=f"q{i}", speaker="int", role="interviewer", text="Tell me more."))
        turns.append(Turn(id=f"a{i}", speaker="pt", role="respondent", text=text))
    idx, pairs = pair_turns(index_turns(turns))
    return PrepResult(turns=idx, qa_pairs=pairs)


def o(key=E1, rel="entails", **kw):
    return {"key": key, "relation": rel, "conf": "high", **kw}


def flag(type_, *keys):
    return {"type": type_, "keys": list(keys), "conf": "high"}


def num(raw, rate):
    return {"raw": raw, "rate_per_week": rate, "bucket_guess": None, "basis": "numeric"}


# id -> (claim text, claim kwargs, evidence replies, verifier output, verdict, concern types)
PAIRS = {
    "rate-vs-count": (
        "Dana misses her evening dose six days a week.",
        {"quantities": [{"kind": "frequency", "raw": "six days a week", "bucket": "always"}]},
        ["I miss the evening dose three or four times a week."],
        {
            "items": [o(frequency=[num("three or four times a week", 3.5)])],
            "flags": [flag("quantity_mismatch", E1)],
        },
        "partially_supported",
        ["frequency_severity_inflation"],
    ),
    "date-vs-count": (
        "Priya has taken 20 mg since last March.",
        {"timeframe": "past"},
        ["I take 20 mg. I started it this June."],
        {"items": [o(timeframe="current")], "flags": [flag("quantity_mismatch", E1)]},
        "insufficient_evidence",
        ["timeframe_mismatch"],
    ),
    "about-ten-vs-ten": (
        "Ten people report to Marcus.",
        {},
        ["About ten, I think. It shifts from month to month."],
        {"items": [o(certainty="hedged_strong")], "flags": [flag("quantity_mismatch", E1)]},
        "partially_supported",
        ["certainty_inflation"],
    ),
    "rounding-dropped-decimals": (
        "The pilot cost $10 million.",
        {},
        ["It came to ten point six million dollars."],
        {"items": [o()]},
        "supported",
        [],
    ),
    "sum-of-given-figures": (
        "Rosa takes 40 mg a day in total.",
        {},
        ["I take 20 mg in the morning.", "Then 10 mg at bedtime."],
        {
            "items": [o(E1), o(E2)],
            "flags": [flag("calculation_error", E1, E2)],
        },
        "partially_supported",
        ["calculation_error"],
    ),
    "figure-never-given": (
        "Tomas leads a team of nine.",
        {},
        ["I lead the platform group."],
        {
            "items": [o(rel="not_addresses")],
            "flags": [flag("quantity_mismatch", E1)],
        },
        "insufficient_evidence",
        ["unsupported_claim"],
    ),
    "previous-medication": (
        "Lena takes 20 mg of sertraline.",
        {},
        ["That was my old medication, citalopram. I took 20 mg of that."],
        {
            "items": [o(rel="contradicts", polarity="negated", experiencer="other_person")],
            "flags": [flag("quantity_mismatch", E1)],
        },
        "contradicted",
        ["wrong_attribution"],
    ),
    "scope-broadening": (
        "Sam avoids all social events.",
        {},
        ["I skip the big parties, but I enjoy dinners with friends."],
        {"items": [o()], "flags": [flag("unsupported_inference", E1)]},
        "partially_supported",
        ["unsupported_inference"],
    ),
    "faithful-generalization": (
        "Sam finds crowds hard.",
        {},
        ["Parties, malls, concerts. I cannot stand any of them."],
        {"items": [o()]},
        "supported",
        [],
    ),
    "merged-facts": (
        "Kim's team of six lost two members in June.",
        {},
        ["My team has six people.", "Two people left the other team in June."],
        {"items": [o(E1), o(E2)], "flags": [flag("element_gap", E1, E2)]},
        "partially_supported",
        ["unsupported_claim"],
    ),
}


def test_ten_pairs():
    assert len(PAIRS) == 10


@pytest.mark.parametrize("name", PAIRS)
async def test_boundary_pair(make_ctx, name):
    text, kw, replies, out, verdict, expected = PAIRS[name]
    prep = prep_for(*replies)
    c = claim(text, reported_by=UNSPEC, **kw)
    lk = link(*(ev(n=n, turn=2 * n - 1, text=replies[n - 1]) for n in range(1, len(replies) + 1)))
    stub = StubClient()
    stub.register("check", lambda req: VerifierOutput.model_validate(out))
    (d,) = await check_claims([c], [lk], prep, prep.turns, make_ctx(llm=stub))
    got = [x.type.value for x in d.concerns]
    assert (d.verdict.value, got) == (verdict, expected), name
    assert not {"frequency_severity_inflation", "quantity_mismatch"} <= set(got)


async def test_figure_only_claim_with_different_figure_is_contradicted(make_ctx):
    """Req 4: a claim whose only content is the figure, against a different figure, is D4."""
    replies = ["Twelve people report to me."]
    prep = prep_for(*replies)
    c = claim("Eight people report to Marcus.", reported_by=UNSPEC)
    lk = link(ev(n=1, turn=1, text=replies[0]))
    out = {"items": [o(rel="contradicts")], "flags": [flag("quantity_mismatch", E1)]}
    stub = StubClient()
    stub.register("check", lambda req: VerifierOutput.model_validate(out))
    (d,) = await check_claims([c], [lk], prep, prep.turns, make_ctx(llm=stub))
    assert (d.verdict.value, [x.type.value for x in d.concerns]) == (
        "contradicted",
        ["quantity_mismatch"],
    )


async def test_previous_medication_fewshot_matches_the_boundary_pair(make_ctx):
    """The few-shot and the `previous-medication` pair read the explicit conflict the same way."""
    from eaudit.check.verifier import load_fewshot

    (shot,) = [
        s
        for s in load_fewshot()
        if s["claim"]["proposition"] == "Jordan reports side effects from Odamet."
    ]
    out = shot["output"]
    assert (out["items"][0]["relation"], out["items"][0]["polarity"]) == ("contradicts", "negated")
    replies = [t["text"] for t in shot["turns"] if t["role"] == "respondent"][-1:]
    prep = prep_for(*replies)
    c = claim(shot["claim"]["proposition"], reported_by=UNSPEC)
    lk = link(ev(n=1, turn=1, text=replies[0]))
    stub = StubClient()
    stub.register("check", lambda req: VerifierOutput.model_validate(out))
    (d,) = await check_claims([c], [lk], prep, prep.turns, make_ctx(llm=stub))
    assert (d.verdict.value, [x.type.value for x in d.concerns]) == (
        PAIRS["previous-medication"][4],
        PAIRS["previous-medication"][5],
    )


# (source replies, claim, atomizer fields, observations, flags, verdict, concern, role)
# Each pair changes the assessment while keeping the supplied interview fixed.
TAXONOMY_PAIRS = {
    "certainty": (
        ["I think the parcel arrived on Tuesday, but I cannot be sure."],
        (
            ("The parcel arrived on Tuesday.", {}, [o(certainty="hedged_strong")], [],
             "partially_supported", ["certainty_inflation"], "supporting"),
            ("The parcel may have arrived on Tuesday.", {"hedged": True},
             [o(certainty="hedged_strong")], [], "supported", [], "supporting"),
        ),
    ),
    "opinion": (
        ["In my opinion, the ridge route is the safest choice."],
        (
            ("The ridge route is the safest choice.", {}, [o(certainty="hedged_strong")],
             [flag("opinion_as_fact", E1), flag("certainty_inflation", E1)],
             "partially_supported", ["opinion_as_fact"], "supporting"),
            ("The participant considers the ridge route the safest choice.",
             {"reported_by": [{"source": "self", "speaker": "pt"}]}, [o()],
             [flag("opinion_as_fact", E1)], "supported", [], "supporting"),
        ),
    ),
    "calculation": (
        ["The red crate held seven lanterns.", "The blue crate held four lanterns."],
        (
            ("The crates held thirteen lanterns in total.", {}, [o(E1), o(E2)],
             [flag("calculation_error", E1, E2), flag("quantity_mismatch", E1, E2)],
             "partially_supported", ["calculation_error"], "supporting"),
            ("The crates held eleven lanterns in total.", {}, [o(E1), o(E2)], [],
             "supported", [], "supporting"),
        ),
    ),
    "quantity": (
        ["The red crate held seven lanterns."],
        (
            ("The red crate held nine lanterns.", {}, [o(rel="contradicts")],
             [flag("calculation_error", E1), flag("quantity_mismatch", E1)],
             "contradicted", ["quantity_mismatch"], "contradicting"),
            ("The red crate held seven lanterns.", {}, [o()], [],
             "supported", [], "supporting"),
        ),
    ),
    "meaning": (
        ["I recommended a walking stick for the hillside path."],
        (
            ("The participant prescribed a walking stick for the hillside path.", {},
             [o(rel="contradicts")], [flag("meaning_shift", E1)],
             "contradicted", ["meaning_shift"], "contradicting"),
            ("The participant suggested a walking stick for the hillside path.", {},
             [o()], [], "supported", [], "supporting"),
        ),
    ),
    "negation": (
        ["I did not recommend a walking stick for the hillside path."],
        (
            ("The participant recommended a walking stick for the hillside path.", {},
             [o(rel="contradicts", polarity="negated")], [flag("meaning_shift", E1)],
             "contradicted", ["negation_reversal"], "contradicting"),
            ("The participant did not recommend a walking stick for the hillside path.",
             {"polarity": "negated"}, [o(polarity="negated")], [],
             "supported", [], "supporting"),
        ),
    ),
    "attribution": (
        ["My aunt recommended a walking stick for the hillside path."],
        (
            ("The participant recommended a walking stick for the hillside path.", {},
             [o(rel="contradicts", experiencer="other_person")], [flag("meaning_shift", E1)],
             "contradicted", ["wrong_attribution"], "contradicting"),
            ("The participant's aunt recommended a walking stick for the hillside path.",
             {"subject": "the participant's aunt"}, [o()], [],
             "supported", [], "supporting"),
        ),
    ),
}


@pytest.mark.parametrize("boundary", TAXONOMY_PAIRS)
@pytest.mark.parametrize("variant", [0, 1], ids=["flagged", "faithful"])
async def test_taxonomy_v2_boundary_pair(make_ctx, boundary, variant):
    replies, variants = TAXONOMY_PAIRS[boundary]
    text, kw, observations, flags, verdict, concerns, role = variants[variant]
    prep = prep_for(*replies)
    c = claim(text, **kw)
    lk = link(*(ev(n=n, turn=2 * n - 1, text=reply) for n, reply in enumerate(replies, 1)))
    stub = StubClient()
    stub.register("check", lambda req: VerifierOutput(items=observations, flags=flags))

    (draft,) = await check_claims([c], [lk], prep, prep.turns, make_ctx(llm=stub))

    assert draft.outcome == "ok"
    assert draft.verdict.value == verdict
    assert [concern.type.value for concern in draft.concerns] == concerns
    assert [(item.key, item.role.value) for item in draft.evidence] == [
        (f"c0.1:e{n}", role) for n in range(1, len(replies) + 1)
    ]
