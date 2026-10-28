"""03 optional: LLM act tagging for unsure turns, rules-only path, soft timeout."""

import asyncio

from eaudit.llm import FailingClient, LLMResult, LLMUnavailable
from eaudit.models import Turn
from eaudit.pipeline.state import RunState
from eaudit.prep import Act, index_turns, prep, prep_rules_only
from eaudit.prep.rules import unsure_acts

A = Act


def turns(*lines: str) -> list[Turn]:
    return [Turn(id=f"t{i}", speaker="ab"[i % 2], text=t) for i, t in enumerate(lines)]


class Tagger:
    """Answers prep_acts calls from a dict {index: [acts]}; records every request."""

    def __init__(self, answers=None):
        self.answers = answers or {}
        self.reqs = []

    async def complete_json(self, req, metrics=None):
        self.reqs.append(req)
        wanted = self._requested(req)
        items = [{"index": i, "acts": self.answers.get(i, [])} for i in wanted]
        return LLMResult(parsed=req.response_model.model_validate({"items": items}), model="t")

    @staticmethod
    def _requested(req):
        return [int(x) for x in req.user.split("TAG:")[1].split("\n")[0].split(",")]


UNSURE = "If it goes past twenty minutes I am gone."  # `if` mid-turn: habitual, not hypothetical
PLAIN = "I forget my keys."


# -- which turns are unsure ------------------------------------------------------------------


def test_unsure_flags():
    t = turns(
        "My manager actually says it is fine.",  # mid-sentence marker
        UNSURE,
        "Do it later.",  # aux opener, not a question
        PLAIN,
        "No wait, I forgot.",  # rule-decided correction: not unsure
        "Can you tell me more?",  # rule-decided question: not unsure
    )
    got = unsure_acts(t, index_turns(t))
    assert got == {0: {A.correction}, 1: {A.hypothetical}, 2: {A.question}}


# -- prep with the LLM -----------------------------------------------------------------------


async def test_off_by_default_makes_no_calls(make_ctx):
    llm = Tagger()
    res = await prep(turns(UNSURE, PLAIN), make_ctx(llm=llm))
    assert llm.reqs == [] and res.degraded_chunks == 0


async def test_on_without_unsure_turns_makes_no_calls(make_ctx):
    llm = Tagger()
    await prep(turns("What about keys?", PLAIN), make_ctx(llm=llm, prep_llm=True))
    assert llm.reqs == []


async def test_unsure_turn_is_tagged_by_one_cheap_call(make_ctx):
    llm = Tagger({1: ["hypothetical"]})
    res = await prep(turns("Any trouble at work?", UNSURE, PLAIN), make_ctx(llm=llm, prep_llm=True))
    assert len(llm.reqs) == 1
    r = llm.reqs[0]
    assert r.tier == "cheap" and r.call_tag == "prep_acts" and r.temperature == 0
    assert A.hypothetical in res.turns[1].acts and res.turns[1].act_source == "llm"
    assert res.turns[0].act_source == "rule" and res.turns[2].act_source == "rule"


async def test_llm_only_replaces_the_unsure_kinds(make_ctx):
    llm = Tagger({1: []})  # the model says: not hypothetical
    res = await prep(turns("Any trouble at work?", UNSURE), make_ctx(llm=llm, prep_llm=True))
    assert res.turns[1].acts == frozenset({A.answer})  # the rule-based answer act is kept


async def test_chunks_run_one_call_each(make_ctx):
    llm = Tagger()
    t = turns(UNSURE, PLAIN, UNSURE, PLAIN, UNSURE)
    await prep(t, make_ctx(llm=llm, prep_llm=True, prep_chunk_turns=2))
    assert len(llm.reqs) == 2
    assert sorted(Tagger._requested(r) for r in llm.reqs) == [[0, 2], [4]]


async def test_context_turns_are_shown_but_not_tagged(make_ctx):
    llm = Tagger()
    t = turns(PLAIN, PLAIN, UNSURE, PLAIN, PLAIN)
    await prep(t, make_ctx(llm=llm, prep_llm=True, prep_context_turns=1))
    user = llm.reqs[0].user
    assert Tagger._requested(llm.reqs[0]) == [2]
    assert "[1]" in user and "[3]" in user and "[0]" not in user and "[4]" not in user


async def test_answer_for_unrequested_turn_degrades_the_chunk(make_ctx):
    class Bad(Tagger):
        async def complete_json(self, req, metrics=None):
            self.reqs.append(req)
            out = {"items": [{"index": 0, "acts": ["question"]}]}
            return LLMResult(parsed=req.response_model.model_validate(out), model="t")

    res = await prep(turns(PLAIN, UNSURE), make_ctx(llm=Bad(), prep_llm=True))
    assert res.degraded_chunks == 1
    assert res.turns[1].act_source == "rule_fallback" and res.turns[0].acts == frozenset()


async def test_llm_failure_falls_back_to_rules_and_never_raises(make_ctx):
    res = await prep(
        turns(PLAIN, UNSURE), make_ctx(llm=FailingClient(LLMUnavailable("down")), prep_llm=True)
    )
    assert res.degraded_chunks == 1 and res.turns[1].act_source == "rule_fallback"


async def test_pairing_uses_the_tagged_acts(make_ctx):
    llm = Tagger({0: ["question"]})
    res = await prep(
        turns("Do it later.", "Fine, I will.", PLAIN), make_ctx(llm=llm, prep_llm=True)
    )
    assert [(p.question_index, p.response_indices) for p in res.qa_pairs] == [(0, (1,))]


# -- rules-only path and soft timeout --------------------------------------------------------


async def test_rules_only_matches_prep_without_llm(make_ctx):
    t = turns("Any trouble at work?", UNSURE, PLAIN)
    assert prep_rules_only(t) == await prep(t, make_ctx())


async def test_soft_timeout_falls_back_to_rules_only(make_ctx, monkeypatch):
    from eaudit.pipeline import flow

    async def slow(turns_, ctx):
        await asyncio.sleep(5)

    monkeypatch.setattr(flow, "prep", slow)
    from eaudit.models import AuditRequest

    req = AuditRequest.model_validate(
        {
            "schema_version": "1.2.0",
            "transcript": [
                t.model_dump(mode="json", exclude_none=True) for t in turns(PLAIN, PLAIN)
            ],
            "assessment": [{"id": "s", "text": "x"}],
        }
    )
    st = RunState()
    await flow.prep_flow(st, req, make_ctx(prep_soft_timeout_s=0.05))
    assert st.prep is not None and len(st.prep.turns) == 2 and st.prep_ready.is_set()


# -- replies to a question only the LLM found -------------------------------------------------


async def test_reply_acts_are_rederived_from_the_merged_questions(make_ctx):
    t = turns("Would often lose keys, then", "Yes.", "Fine.")
    off = await prep(t, make_ctx())
    assert off.turns[1].acts == frozenset({A.backchannel}) and off.qa_pairs == []
    on = await prep(t, make_ctx(llm=Tagger({0: ["question"]}), prep_llm=True))
    assert on.turns[0].acts >= {A.question}
    assert on.turns[1].acts == frozenset({A.answer}) and on.turns[1].responds_to == 0


async def test_longer_reply_becomes_an_answer_and_a_new_question_is_not_one(make_ctx):
    t = turns("Would often lose keys, then", "I lose them weekly.", "Do it later.")
    res = await prep(t, make_ctx(llm=Tagger({0: ["question"], 2: ["question"]}), prep_llm=True))
    assert A.answer in res.turns[1].acts
    assert A.question in res.turns[2].acts and A.answer not in res.turns[2].acts


async def test_llm_detected_question_and_yes_is_endorsed_not_non_answer(make_ctx):
    from eaudit.link.validate import answer_status

    res = await prep(
        turns("Would often lose keys, then", "Yes."),
        make_ctx(llm=Tagger({0: ["question"]}), prep_llm=True),
    )
    assert answer_status([0, 1], res) == "endorsed"
