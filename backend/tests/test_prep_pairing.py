from eval.adhd import load_spec
from iaudit_backend.llm import FailingClient, LLMUnavailable
from iaudit_backend.models import Turn
from iaudit_backend.prep import Act, QAPair, prep


def turns(*pairs: tuple[str, str], roles=False) -> list[Turn]:
    return [
        Turn(id=f"t{i}", speaker=s, text=t, **({"role": "interviewer"} if roles else {}))
        for i, (s, t) in enumerate(pairs)
    ]


def adhd() -> list[Turn]:
    return [
        Turn.model_validate({k: v for k, v in t.items() if k != "role"})
        for t in load_spec()["transcript"]
    ]


async def test_adhd_pairs_without_any_roles(make_ctx):
    res = await prep(adhd(), make_ctx())
    pairs = {p.question_index: p.response_indices for p in res.qa_pairs}
    assert pairs[0] == (1,) and pairs[2] == (3,)
    assert pairs[12] == (13,)  # backchannel responses are included
    assert pairs[18] == (19,) and pairs[22] == (23,)
    assert all(t.role is None for t in res.turns)  # role stays None


async def test_responds_to_is_set_on_responses(make_ctx):
    res = await prep(adhd(), make_ctx())
    by = {t.index: t.responds_to for t in res.turns}
    assert by[1] == 0 and by[3] == 2 and by[13] == 12
    assert by[0] is None and by[14] is None
    assert Act.backchannel in res.turns[13].acts


async def test_roles_do_not_change_pairing(make_ctx):
    t = adhd()
    with_roles = [Turn.model_validate(x) for x in load_spec()["transcript"]]
    a = await prep(t, make_ctx())
    b = await prep(with_roles, make_ctx())
    assert a.qa_pairs == b.qa_pairs


async def test_multiple_responses_until_questioner_speaks_again(make_ctx):
    res = await prep(
        turns(
            ("c", "How are you?"), ("a", "Fine."), ("b", "Me too."), ("c", "Good."), ("a", "Hm.")
        ),
        make_ctx(),
    )
    assert res.qa_pairs == [QAPair(0, (1, 2))]
    assert [t.responds_to for t in res.turns] == [None, 0, 0, None, None]


async def test_next_question_from_another_speaker_ends_the_set(make_ctx):
    res = await prep(
        turns(
            ("c", "How are you?"),
            ("a", "Fine."),
            ("b", "Do you two want coffee?"),
            ("a", "Yes."),
        ),
        make_ctx(),
    )
    pairs = {p.question_index: p.response_indices for p in res.qa_pairs}
    assert pairs == {0: (1,), 2: (3,)}


async def test_question_answering_a_question_gets_both_links(make_ctx):
    res = await prep(
        turns(
            ("c", "Did you sleep?"), ("a", "Why do you ask?"), ("c", "It matters."), ("a", "No.")
        ),
        make_ctx(),
    )
    pairs = {p.question_index: p.response_indices for p in res.qa_pairs}
    assert pairs == {0: (1,), 1: (2,)}
    assert res.turns[1].responds_to == 0 and Act.question in res.turns[1].acts


async def test_question_with_no_response_makes_no_pair(make_ctx):
    res = await prep(turns(("c", "Anything else?")), make_ctx())
    assert res.qa_pairs == [] and res.turns[0].responds_to is None


async def test_same_speaker_follow_up_is_not_a_response(make_ctx):
    res = await prep(
        turns(("c", "Do you nap?"), ("c", "Sorry, do you sleep?"), ("a", "No.")), make_ctx()
    )
    pairs = {p.question_index: p.response_indices for p in res.qa_pairs}
    assert 0 not in pairs and pairs == {1: (2,)}


async def test_prep_makes_no_llm_calls(make_ctx):
    ctx = make_ctx(llm=FailingClient(LLMUnavailable("must not be called")))
    await prep(adhd(), ctx)
    assert ctx.metrics.records == []
