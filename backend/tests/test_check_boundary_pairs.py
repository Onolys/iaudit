"""Ten fictional boundary pairs for the quantity check (taxonomy v1, Req 10).

Each pair scripts the verifier output (no LLM, no network) and asserts the exact concern set the
pipeline settles on. The scripted outputs are what a careful verifier returns; the first and
sixth also carry a stray `quantity_mismatch` flag to pin the precedence and grounding rules.
"""

import pytest
from check_helpers import claim, ev, link

from iaudit_backend.check import check_claims
from iaudit_backend.check.models import VerifierOutput
from iaudit_backend.llm import StubClient
from iaudit_backend.models import Turn
from iaudit_backend.prep import PrepResult, index_turns, pair_turns

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
        {"items": [o(timeframe="current")]},
        "insufficient_evidence",
        ["timeframe_mismatch"],
    ),
    "about-ten-vs-ten": (
        "Ten people report to Marcus.",
        {},
        ["About ten, I think. It shifts from month to month."],
        {"items": [o(certainty="hedged_strong")]},
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
            "flags": [flag("quantity_mismatch", E1, E2)],
        },
        "partially_supported",
        ["quantity_mismatch"],
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
        {"items": [o(rel="contradicts", polarity="negated", experiencer="other_person")]},
        "contradicted",
        ["wrong_attribution"],
    ),
    "scope-broadening": (
        "Sam avoids all social events.",
        {},
        ["I skip the big parties, but I enjoy dinners with friends."],
        {"items": [o()], "flags": [flag("context_stripping", E1)]},
        "partially_supported",
        ["context_stripping"],
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
