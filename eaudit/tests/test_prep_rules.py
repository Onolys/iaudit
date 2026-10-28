import pytest

from eaudit.models import Turn
from eaudit.prep import Act, index_turns
from eval.adhd import load_spec

A = Act


def adhd() -> list[Turn]:
    return [Turn.model_validate(t) for t in load_spec()["transcript"]]


def acts(*lines: str) -> list[frozenset]:
    """lines alternate speakers a, b, a, b..."""
    turns = [Turn(id=f"t{i}", speaker="ab"[i % 2], text=t) for i, t in enumerate(lines)]
    return [t.acts for t in index_turns(turns)]


def test_adhd_acceptance_turns():
    by = {t.index: t.acts for t in index_turns(adhd())}
    assert by[1] == {A.answer}  # "if it goes past twenty minutes" is habitual, not hypothetical
    assert by[3] == {A.answer}
    assert by[5] == {A.answer}  # "my manager actually says" is emphasis, not correction
    assert by[11] == {A.answer, A.correction}
    assert by[13] == {A.backchannel}  # "Hm." is not an answer
    assert A.question in by[0] and A.question in by[2] and A.question in by[24]
    assert A.question in by[8] and A.question in by[20]  # "And keys?", "Anything else?"


def test_index_fields_and_roles_are_copied_not_inferred():
    turns = [
        Turn(id="x", speaker="p", role="respondent", text="Yes."),
        Turn(id="y", speaker="p", text="Fine."),
    ]
    out = index_turns(turns)
    assert [(t.index, t.id, t.role, t.length, t.act_source) for t in out] == [
        (0, "x", "respondent", 4, "rule"),
        (1, "y", None, 5, "rule"),
    ]
    assert out[1].role is None  # never propagated from the same speaker's other turn
    assert out[0].responds_to is None and out[0].text == "Yes."


def test_empty_text_has_no_acts():
    assert acts("", "") == [frozenset(), frozenset()]


@pytest.mark.parametrize(
    "text",
    [
        "Do you often forget things?",
        "Did you see a doctor",
        "What happened next?",
        "How often does that happen",
        "Tell me about your week.",
        "Describe a typical day.",
        "Walk me through the morning.",
        "That is fine. Are you sure?",
        "Are you okay?",
    ],
)
def test_question_yes(text):
    assert A.question in acts(text)[0]


@pytest.mark.parametrize(
    "text",
    [
        "It was fine, you know?",
        "Right?",
        "That is how it goes, right?",
        "I hid it, y'know?",
        "I do it all the time.",
        "Do it later.",
        "Whatever happens happens.",
    ],
)
def test_question_no(text):
    assert A.question not in acts(text)[0]


@pytest.mark.parametrize(
    "text", ["Hm.", "Mm-hmm.", "Uh-huh.", "Right.", "Okay.", "I see.", "Got it.", "Sure."]
)
def test_pure_continuers_are_backchannel_even_after_a_question(text):
    out = acts("Do you forget things?", text)
    assert out[1] == {A.backchannel}


@pytest.mark.parametrize("text", ["Yeah.", "Yes", "No.", "Nope", "Yep.", "Yeah yeah."])
def test_polar_after_other_speakers_question_is_answer(text):
    assert acts("Do you forget things?", text)[1] == {A.answer}


def test_polar_elsewhere_is_backchannel():
    assert acts("I forgot my keys.", "Yeah.")[1] == {A.backchannel}
    # same speaker's own question does not make it an answer
    turns = [
        Turn(id="a", speaker="s", text="Do you forget?"),
        Turn(id="b", speaker="s", text="No."),
    ]
    assert index_turns(turns)[1].acts == {A.backchannel}


def test_answer_is_position_only_and_not_for_questions():
    out = acts("Do you forget things?", "Sometimes, when I am tired.", "Do you nap?")
    assert out[1] == {A.answer}
    assert A.answer not in out[2]
    assert acts("Hello there.", "It is raining.")[1] == frozenset()


def test_answer_needs_different_speaker_string():
    turns = [
        Turn(id="a", speaker="s", text="Do you forget things?"),
        Turn(id="b", speaker="s", text="Sometimes."),
    ]
    assert index_turns(turns)[1].acts == frozenset()


@pytest.mark.parametrize(
    "text",
    [
        "Actually, it was Tuesday.",
        "I mean, it was Tuesday.",
        "No wait, it was Tuesday.",
        "Sorry, it was Tuesday.",
        "Let me correct that.",
        "What I meant was Tuesday.",
        "Scratch that.",
        "I misspoke earlier.",
        "Rather, it was Tuesday.",
        "It was Monday. Actually, Tuesday.",
    ],
)
def test_correction_sentence_initial(text):
    assert A.correction in acts("Q?", text)[1]


@pytest.mark.parametrize(
    "text",
    ["My manager actually says it is fine.", "It was, I mean, a quiet day.", "He is rather tall."],
)
def test_correction_mid_sentence_is_not_a_correction(text):
    assert A.correction not in acts("Q?", text)[1]


@pytest.mark.parametrize(
    "text",
    [
        "Suppose you had to leave, what would you do.",
        "Imagine she could stay.",
        "Let's say he would call.",
        "What if it might rain.",
        "If I were rich I'd travel.",
        "Say you should go.",
    ],
)
def test_hypothetical_yes(text):
    assert A.hypothetical in acts("Q?", text)[1]


@pytest.mark.parametrize(
    "text",
    [
        "If it goes past twenty minutes I'm gone.",
        "I would never do that.",
        "Suppose.",
        "We could go.",
    ],
)
def test_hypothetical_no(text):
    assert A.hypothetical not in acts("Q?", text)[1]


def test_acts_are_multi_label_frozensets():
    (_, second) = acts("Do you forget?", "Actually, it was. If I could I would. Do you?")
    assert second == {A.correction, A.hypothetical, A.question}
    assert isinstance(second, frozenset)
