from check_helpers import adhd_prep, claim, ev, link

from eaudit.check.group_a import run_group_a

PREP = adhd_prep(roles=True)
NOROLE = adhd_prep(roles=False)


def rb(*pairs):
    return [{"source": s, "speaker": sp} for s, sp in pairs]


def test_unspecified_source_accepts_every_speaker():
    c = claim("He forgets.")
    ga = run_group_a(c, link(ev(turn=21)), PREP.turns)
    assert ga.attribution == {"c0.1:e1": "ok"}


def test_reporter_mismatch_by_speaker_string():
    c = claim("Alex forgets.", reported_by=rb(("self", "alex1")))
    ga = run_group_a(c, link(ev(n=1, turn=3), ev(n=2, turn=19)), PREP.turns)
    assert ga.attribution == {"c0.1:e1": "ok", "c0.1:e2": "mismatch"}


def test_reporter_mismatch_by_role():
    c = claim("Alex forgets.", reported_by=rb(("informant", None)))
    ga = run_group_a(c, link(ev(n=1, turn=3), ev(n=2, turn=19)), PREP.turns)
    assert ga.attribution == {"c0.1:e1": "mismatch", "c0.1:e2": "ok"}


def test_role_none_skips_attribution_and_lands_in_ambiguous():
    c = claim("Alex forgets.", reported_by=rb(("self", "alex1")))
    ga = run_group_a(c, link(ev(turn=19), ambiguous=[2]), NOROLE.turns)
    assert ga.attribution == {"c0.1:e1": "skip"}
    assert ga.ambiguous == [2, 19] and ga.role_skipped == 1


def test_role_other_skips_role_entry():
    turns = list(PREP.turns)
    from dataclasses import replace

    from eaudit.models import Role

    turns[19] = replace(turns[19], role=Role.other)
    c = claim("Alex forgets.", reported_by=rb(("informant", None)))
    ga = run_group_a(c, link(ev(turn=19)), turns)
    assert ga.attribution["c0.1:e1"] == "skip" and ga.ambiguous == []


def test_assessor_entry_means_no_reporter_check():
    c = claim("Alex forgets.", reported_by=rb(("assessor", None), ("self", "alex1")))
    ga = run_group_a(c, link(ev(turn=19)), PREP.turns)
    assert ga.attribution["c0.1:e1"] == "ok"


def test_a9_fires_for_interviewer_question_turn():
    c = claim("He is easily distracted.")
    ga = run_group_a(
        c, link(ev(turns=[12, 13], status="non_answer", role="qualifying")), PREP.turns
    )
    assert ga.no_call and ga.question_as_answer == ["c0.1:e1"]


def test_a9_skips_when_question_role_missing():
    c = claim("He is easily distracted.")
    ga = run_group_a(
        c, link(ev(turns=[12, 13], status="non_answer", role="qualifying")), NOROLE.turns
    )
    assert ga.no_call and ga.question_as_answer == [] and 12 in ga.ambiguous


def test_a9_does_not_fire_when_respondent_asks():
    c = claim("He is easily distracted.")
    ga = run_group_a(c, link(ev(turns=[3], status="question_only", role="qualifying")), PREP.turns)
    # turn 3 is an answer turn, not a question; falls back to the first segment's role
    assert ga.no_call and ga.question_as_answer == []


def test_a9_not_fired_with_endorsed_evidence():
    c = claim("He is easily distracted.")
    lk = link(
        ev(n=1, turns=[12, 13], status="non_answer", role="qualifying"),
        ev(n=2, turn=3, status="endorsed"),
    )
    ga = run_group_a(c, lk, PREP.turns)
    assert not ga.no_call and ga.question_as_answer == []


def test_endorsed_or_na_evidence_needs_a_call():
    ga = run_group_a(claim("x"), link(ev(status="n/a")), PREP.turns)
    assert not ga.no_call
