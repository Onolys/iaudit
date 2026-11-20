"""Fictional prompt examples must agree with deterministic synthesis, offline.

These checks catch examples that teach a new flag but fail its code gate, or flag
faithful attribution, arithmetic, paraphrase or generalization.
"""

import pytest
from check_helpers import claim, ev, link

from eaudit.check import check_claims
from eaudit.check.models import VerifierOutput
from eaudit.check.verifier import load_fewshot
from eaudit.llm import StubClient
from eaudit.models import Turn
from eaudit.prep import PrepResult, index_turns, pair_turns

CASES = [
    ("The amber lamp makes Jordan restless.", "opinion_as_fact"),
    ("Jordan believes the amber lamp causes restlessness.", None),
    ("Jordan packed nine ceramic tiles in total.", "calculation_error"),
    ("Jordan packed seven ceramic tiles in total.", None),
    ("Jordan authorized the mural sketch.", "meaning_shift"),
    ("Jordan proposed using the mural sketch.", None),
    ("The whole pottery circle opposed the new kiln.", "unsupported_inference"),
    ("Some pottery circle members opposed the new kiln.", None),
]


@pytest.mark.parametrize("proposition,expected", CASES)
async def test_taxonomy_prompt_example_reaches_the_expected_decision(make_ctx, proposition, expected):
    matches = [s for s in load_fewshot() if s["claim"]["proposition"] == proposition]
    assert len(matches) == 1, f"missing or duplicated boundary example: {proposition}"
    shot = matches[0]
    turns = [Turn(id=str(t["i"]), speaker=t["speaker"], role=t["role"], text=t["text"])
             for t in shot["turns"]]
    indexed, pairs = pair_turns(index_turns(turns))
    prep = PrepResult(turns=indexed, qa_pairs=pairs)
    positions = {t["i"]: i for i, t in enumerate(shot["turns"])}
    evidence = []
    for n, e in enumerate(shot["evidence"], 1):
        assert e["text"] in shot["turns"][positions[e["turns"][0]]]["text"]
        evidence.append(ev(n=n, turn=positions[e["turns"][0]], text=e["text"],
                           role=e["linker_role"], status=e["answer_status"]))
    reporter = shot["claim"]["reported_by"][0]
    reported_by = [{"source": "self" if reporter == "jordan1" else "unspecified",
                    "speaker": reporter if reporter == "jordan1" else None}]
    c = claim(proposition, reported_by=reported_by, hedged=shot["claim"]["hedged"])
    stub = StubClient()
    stub.register("check", lambda req: VerifierOutput.model_validate(shot["output"]))
    (decision,) = await check_claims([c], [link(*evidence)], prep, indexed, make_ctx(llm=stub))
    assert (decision.verdict.value, [x.type.value for x in decision.concerns]) == (
        "partially_supported" if expected else "supported", [expected] if expected else []
    )
