import json
import re

import pytest
from link_helpers import adhd_prep, adhd_turns, claim

from iaudit_backend.link.models import LinkerOutput
from iaudit_backend.link.prompt import (
    FEWSHOT_PATH,
    build_prompt,
    load_fewshot,
    render_turns,
    stage_block,
)
from iaudit_backend.models import Turn
from iaudit_backend.prep import PrepResult, index_turns, pair_turns


def prep_of(turns):
    ts, pairs = pair_turns(index_turns(turns))
    return PrepResult(ts, pairs)


def test_turn_format_role_unknown_and_text_untouched():
    turns = [
        Turn(id="1", speaker="a", role="interviewer", text='Say "x" <b>&amp; y</b>'),
        Turn(id="2", speaker="b", text="plain"),
    ]
    out = render_turns(turns, [0, 1])
    assert '<turn i="0" speaker="a" role="interviewer">Say "x" <b>&amp; y</b></turn>' in out
    assert '<turn i="1" speaker="b" role="unknown">plain</turn>' in out


def test_gaps_get_omitted_markers_including_edges():
    turns = adhd_turns()
    out = render_turns(turns, [3, 4, 9])
    assert "[... turns 0-2 omitted ...]" in out
    assert "[... turns 5-8 omitted ...]" in out
    assert "[... turns 10-25 omitted ...]" in out
    assert render_turns(turns, list(range(26))).count("omitted") == 0
    assert "[... turn 1 omitted ...]" in render_turns(turns, [0, 2])


def test_whole_mode_prefix_is_identical_across_claims_and_has_no_act_hints():
    turns, prep = adhd_turns(), adhd_prep()
    a = build_prompt(claim("Alex naps."), turns, prep, list(range(26)), "whole")
    b = build_prompt(
        claim("He forgets groceries.", cid="c0.2"), turns, prep, list(range(26)), "whole"
    )
    assert a[0] == b[0] and a[1] == b[1]  # cache_prefix and system byte-identical
    assert a[2] != b[2]
    assert "hints" not in a[0] and "question" not in a[0].split("# Transcript")[1]
    assert "Heuristic dialogue-act hints" in a[2] and "12=question" in a[2]
    assert "<turn i=" not in a[2]  # transcript lives in the prefix only


def test_shortlist_mode_prefix_has_no_transcript_and_user_carries_turns():
    turns, prep = adhd_turns(), adhd_prep()
    p, s, u = build_prompt(claim("Alex naps."), turns, prep, [12, 13], "shortlist")
    assert "# Transcript" not in p and "Output schema" in p and "Example 1" in p
    assert '<turn i="12"' in u and '<turn i="13"' in u and '<turn i="14"' not in u
    assert "[... turns 0-11 omitted ...]" in u and "12=question, 13=backchannel" in u
    q = build_prompt(claim("Other claim."), turns, prep, [3], "shortlist")
    assert q[0] == p  # prefix does not depend on the claim or the shortlist


def test_claim_block_shape():
    c = claim(
        "Alex naps daily.",
        quantities=["daily"],
        reported_by=[{"source": "informant", "speaker": "sam1"}],
        polarity="negated",
        timeframe="past",
    )
    u = build_prompt(c, adhd_turns(), adhd_prep(), [0], "shortlist")[2]
    assert "Claim: Alex naps daily." in u and "Reported by: informant:sam1" in u
    assert "Polarity: negated" in u and "Timeframe: past" in u and "Quantities: daily" in u


def test_prompt_names_no_model_ids():
    p = build_prompt(claim("x"), adhd_turns(), adhd_prep(), [0], "shortlist")
    assert not re.search(r"claude|anthropic|gpt|opus|sonnet|haiku|gemini|litellm", p[0], re.I)


def test_schema_and_rules_are_in_the_prompt():
    s = stage_block()
    for k in ["items", "link_type", "premises", "inference_step", "segments"]:
        assert f'"{k}"' in s
    sys_ = build_prompt(claim("x"), adhd_turns(), adhd_prep(), [0], "shortlist")[0].lower()
    for needle in [
        "character-for-character",
        "contradicting",
        "qualifying",
        "never guess a speaker",
    ]:
        assert needle in sys_


def test_fewshot_loads_and_covers_the_required_cases():
    raw = json.loads(FEWSHOT_PATH.read_text(encoding="utf-8"))
    assert raw["split"] == "prompt" and len(raw["examples"]) == 7
    outs = [LinkerOutput.model_validate(e["output"]) for e in load_fewshot()]
    items = [i for o in outs for i in o.items]
    assert {"quote", "paraphrase", "inference"} <= {i.link_type for i in items}
    assert {"supporting", "contradicting", "qualifying"} <= {i.role.value for i in items}
    assert any(not o.items for o in outs)  # nothing found
    assert any(len(i.segments) == 2 for i in items)  # question + reply


@pytest.mark.parametrize("n", range(7))
def test_fewshot_excerpts_are_verbatim_single_turn_and_premises_resolve(n):
    ex = load_fewshot()[n]
    by_turn = {t["i"]: t["text"] for t in ex["turns"]}
    out = LinkerOutput.model_validate(ex["output"])
    keys = {i.key for i in out.items}
    for it in out.items:
        for s in it.segments:
            assert s.text in by_turn[s.turn]
        if it.link_type == "inference":
            assert not it.segments and it.inference_step and set(it.premises) <= keys - {it.key}


def test_fewshot_never_reuses_eval_material():
    blob = FEWSHOT_PATH.read_text(encoding="utf-8").lower()
    for banned in ["alex", "sam1", "clinician1", "phone", "keys", "paint", "meeting", "attention",
                   "careless", "groceries", "errands", "bathroom", "daydream", "report card"]:  # fmt: skip
        assert banned not in blob, banned
