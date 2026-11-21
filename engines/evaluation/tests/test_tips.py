"""R5/D7/D8/D9/AC7: tips proposed by the model, validated in code; stub client only."""

import asyncio
import json
import re
from pathlib import Path

import pytest
from onolys_core.llm import LLMBadOutput, StubClient
from onolys_core.llm.fixture_client import FailingClient
from onolys_core.transcript import Transcript
from paudit.pack import load_pack
from paudit.result import PauditResult

from onolys_evaluation.tips import ROUTE, generate_tips

pytestmark = pytest.mark.unit

PACK_DIR = Path(__file__).resolve().parents[3] / "protocols" / "miti-4.2.1"
FIX = PACK_DIR / "fixtures" / "evaluation"

# (item, clinician turn, quote copied from the fixture transcript)
Q = {
    "t4": "What makes walking more important to you right now?",
    "t6": "You want to be there for your kids",
    "t9": "Where would a walk fit best in your week?",
    "t11": "Three days a week at lunchtime feels doable to you.",
    "t13": "Why a six and not a three?",
    "t15": "Would it be helpful if I shared some ideas",
    "t17": "What would you like to",
}
ITEMS = ["cct", "sst", "partnership", "empathy", "cr", "question"]


@pytest.fixture(scope="module")
def pack():
    return load_pack(PACK_DIR)


@pytest.fixture(scope="module")
def transcript():
    return Transcript.model_validate(json.loads((FIX / "transcript.json").read_text("utf-8")))


@pytest.fixture(scope="module")
def smap():
    return json.loads((FIX / "speaker_map.json").read_text("utf-8"))


@pytest.fixture(scope="module")
def result():
    return PauditResult.model_validate(json.loads((FIX / "paudit_result.json").read_text("utf-8")))


def tip(item="cct", turn="t4", quote=None, alt="Try reflecting the goal first, then ask.", **kw):
    return {
        "item_id": item,
        "observation": kw.get("observation", "Onolys reads this as a closed prompt."),
        "quote": {"turn_id": turn, "text": quote if quote is not None else Q[turn]},
        "alternative": alt,
        "why_it_matters": kw.get("why", "Open wording invites more of the client's own reasons."),
    }


def good(n):
    specs = [("cct", "t4"), ("sst", "t6"), ("partnership", "t9"), ("empathy", "t11"),
             ("cr", "t13"), ("question", "t15"), ("gi", "t17")]
    return [tip(i, t, alt=f"Try option {k} in plain words.") for k, (i, t) in enumerate(specs[:n])]


def run(replies, pack, transcript, smap, result):
    """replies: list of dicts (returned in order) or exceptions to raise."""
    stub, seen = StubClient(), []

    def handler(req):
        seen.append(req)
        r = replies[len(seen) - 1]
        if isinstance(r, BaseException):
            raise r
        return {"tips": r}

    for tag in ("tips:r0", "tips:r0:retry"):
        stub.register(tag, handler)
    out = asyncio.run(generate_tips(stub, pack, transcript, smap, result))
    return out, seen


def codes(warnings):
    return [w.code for w in warnings]


def test_valid_three_to_five_ranked_with_real_offsets(pack, transcript, smap, result):
    (art, warns), seen = run([good(7)], pack, transcript, smap, result)
    assert len(seen) == 1 and seen[0].tier == ROUTE == "tips"
    assert [t.rank for t in art.valid] == [1, 2, 3, 4, 5]  # first five kept
    assert warns == [] and len(art.proposals) == 7
    turns = {t.id: t.text for t in transcript.turns}
    for t in art.valid:
        q = t.quote
        assert turns[q.turn_id][q.start:q.end] == q.text


def test_quote_replaced_by_actual_substring(pack, transcript, smap, result):
    sloppy = tip("cct", "t4", quote="what makes  walking more important to you right now")
    (art, _), _ = run([[sloppy, *good(3)[1:]], ], pack, transcript, smap, result)
    first = art.valid[0].quote
    assert first.text == "What makes walking more important to you right now"
    assert first.text == transcript.turns[3].text[first.start:first.end]


def test_invented_quote_rejected(pack, transcript, smap, result):
    bad = tip("cct", "t4", quote="Have you considered joining a gym this month?")
    (art, _), seen = run([[bad, *good(3)], [bad]], pack, transcript, smap, result)
    assert all(t.quote.text != bad["quote"]["text"] for t in art.valid)
    assert len(art.valid) == 3


def test_non_clinician_turn_rejected(pack, transcript, smap, result):
    client_tip = tip("cct", "t3", quote="I sit at a desk all day")
    (art, _), _ = run([[client_tip, *good(3)]], pack, transcript, smap, result)
    assert [t.quote.turn_id for t in art.valid] == ["t4", "t6", "t9"]


def test_unknown_item_and_unknown_turn_rejected(pack, transcript, smap, result):
    bad = [tip("nope", "t4"), tip("cct", "t99", quote="x"), *good(4)[1:]]
    (art, _), _ = run([bad], pack, transcript, smap, result)
    assert [t.item_id for t in art.valid] == ["sst", "partnership", "empathy"]


def test_banned_tone_rejected(pack, transcript, smap, result):
    bad = tip("cct", "t4", alt="You should have asked about the goal.")
    bad2 = tip("sst", "t6", observation="This was a mistake.")
    (art, _), _ = run([[bad, bad2, *good(5)[2:]]], pack, transcript, smap, result)
    assert [t.item_id for t in art.valid] == ["partnership", "empathy", "cr"]


def test_alternative_rules(pack, transcript, smap, result):
    empty = tip("cct", "t4", alt="   ")
    long = tip("sst", "t6", alt="One idea. Two ideas. Three ideas.")
    same = tip("partnership", "t9", alt=Q["t9"])
    two_ok = tip("empathy", "t11", alt="Name the feeling first. Then check it out.")
    (art, _), _ = run([[empty, long, same, two_ok, *good(7)[4:]]], pack, transcript, smap, result)
    assert [t.item_id for t in art.valid] == ["empathy", "cr", "question", "gi"]


def test_caps_two_per_item_one_per_item_turn(pack, transcript, smap, result):
    a = tip("cct", "t4", alt="Alt a one.")
    dup = tip("cct", "t4", quote="important to you right now", alt="Alt b one.")  # same (item,turn)
    b = tip("cct", "t6", alt="Alt c one.")
    c = tip("cct", "t9", alt="Alt d one.")  # third for cct
    (art, _), _ = run([[a, dup, b, c, *good(5)[1:4]]], pack, transcript, smap, result)
    got = [(t.item_id, t.quote.turn_id) for t in art.valid]
    assert got.count(("cct", "t4")) == 1
    assert sum(1 for i, _ in got if i == "cct") == 2
    assert len(got) == 5


def test_retry_lists_violations_then_fewer_tips(pack, transcript, smap, result):
    first = [good(1)[0], tip("cct", "t6", quote="made up words here")]
    second = [tip("sst", "t6")]
    (art, warns), seen = run([first, second], pack, transcript, smap, result)
    assert len(seen) == 2 and seen[1].call_tag == "tips:r0:retry"
    assert "violations" not in json.loads(seen[0].user)
    v = json.loads(seen[1].user)["violations"]
    assert any(x["code"] == "quote_not_found" for x in v)
    assert "made up words here" not in seen[1].user  # codes only, no offending text
    assert [t.item_id for t in art.valid] == ["cct", "sst"]
    assert codes(warns) == ["fewer_tips"]
    assert len(art.proposals) == 3


def test_retry_reaches_three_no_warning(pack, transcript, smap, result):
    (art, warns), seen = run([good(1), good(4)[1:]], pack, transcript, smap, result)
    assert len(art.valid) == 4 and warns == [] and len(seen) == 2


def test_zero_valid_ships_empty_with_fewer_tips(pack, transcript, smap, result):
    bad = [tip("cct", "t3", quote="I sit at a desk all day")]
    (art, warns), seen = run([bad, bad], pack, transcript, smap, result)
    assert art.valid == [] and codes(warns) == ["fewer_tips"] and len(seen) == 2


def test_call_error_is_tips_failed(pack, transcript, smap, result):
    stub = FailingClient(RuntimeError("boom"))
    art, warns = asyncio.run(generate_tips(stub, pack, transcript, smap, result))
    assert art.valid == [] and art.proposals == [] and codes(warns) == ["tips_failed"]


def test_bad_output_twice_is_tips_failed(pack, transcript, smap, result):
    bad = LLMBadOutput("truncated")
    (art, warns), seen = run([bad, bad], pack, transcript, smap, result)
    assert len(seen) == 2 and art.valid == [] and codes(warns) == ["tips_failed"]


def test_bad_output_then_good_recovers(pack, transcript, smap, result):
    (art, warns), _ = run([LLMBadOutput("x"), good(3)], pack, transcript, smap, result)
    assert len(art.valid) == 3 and warns == []


def test_prompt_has_no_clinician_rating_or_diff(pack, transcript, smap, result):
    (_, _), seen = run([good(3)], pack, transcript, smap, result)
    req = seen[0]
    blob = json.dumps(
        [req.system, req.user, req.cache_prefixes, req.cache_prefix], ensure_ascii=False
    ).lower()
    for word in ("clinician_rating", "clinician rating", "diff", "differs", "flagged", "agree",
                 "within_one", "self-rating", "self_rating", "rating card"):
        assert not re.search(rf"\b{re.escape(word)}\b", blob), word
    user = json.loads(req.user)
    assert set(user) == {"change_goal", "onolys", "clinician_turns"}
    assert set(user["onolys"]) == {"counts", "instances", "globals", "summaries"}
    # clinician turns only, each with the preceding client turn as context
    ids = [t["turn_id"] for t in user["clinician_turns"]]
    assert "t3" not in ids and "t4" in ids
    t4 = next(t for t in user["clinician_turns"] if t["turn_id"] == "t4")
    assert t4["preceding_client_turn"]["turn_id"] == "t3"
    assert "temperature" not in req.__dict__ or req.temperature == 0.0
