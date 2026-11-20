"""Group A: code-only checks (reporter attribution, question-as-answer, missing-role rule).

A turn missing a speaker or role is excluded from every speaker-dependent check: its identity is
unreliable (for example after a diarization merge). The check is skipped, never guessed, and the
turn is reported through `ambiguous` so 02 can warn.
"""

from dataclasses import dataclass, field
from typing import Literal

from eaudit.atomize.models import AtomicClaim
from eaudit.link.models import LinkResult
from eaudit.models import Role
from eaudit.prep import Act, IndexedTurn

Attribution = Literal["ok", "mismatch", "skip"]
_NON_ENDORSED = ("question_only", "non_answer")
_ROLE_FOR_SOURCE = {"self": Role.respondent, "informant": Role.informant}


@dataclass
class GroupA:
    attribution: dict[str, Attribution] = field(default_factory=dict)  # evidence key -> result
    ambiguous: list[int] = field(default_factory=list)
    question_as_answer: list[str] = field(default_factory=list)  # keys, when A9 fires
    no_call: bool = False  # every item is non-endorsed: decided without the verifier
    role_skipped: int = 0


def _answer_turns(seg_turns: list[int], turns: list[IndexedTurn]) -> list[int]:
    return [i for i in seg_turns if turns[i].role != Role.interviewer]


def _turn_match(claim: AtomicClaim, t: IndexedTurn) -> Literal["match", "skip", "mismatch"]:
    if t.role is None or t.speaker is None:
        return "skip"
    saw_skip = False
    for e in claim.reported_by:
        if e.speaker is not None:
            if t.speaker == e.speaker:
                return "match"
            continue
        if t.role == Role.other:
            saw_skip = True
        elif t.role == _ROLE_FOR_SOURCE[e.source]:
            return "match"
    return "skip" if saw_skip else "mismatch"


def _checkable(claim: AtomicClaim) -> bool:
    """Reporters are checked only when every entry names a speaker or a self/informant source."""
    return all(e.speaker is not None or e.source in _ROLE_FOR_SOURCE for e in claim.reported_by)


def run_group_a(claim: AtomicClaim, link: LinkResult, turns: list[IndexedTurn]) -> GroupA:
    ga = GroupA(ambiguous=list(link.ambiguous_turns))
    items = [e for e in link.evidence if e.link_type != "inference"]
    check_reporters = _checkable(claim)
    for e in items:
        seg = [i for i in [s.turn_index for s in e.draft.segments] if 0 <= i < len(turns)]
        result: Attribution = "ok"
        if check_reporters:
            res = [_turn_match(claim, turns[i]) for i in _answer_turns(seg, turns)]
            for i in _answer_turns(seg, turns):
                if turns[i].role is None or turns[i].speaker is None:
                    ga.role_skipped += 1
                    ga.ambiguous.append(i)
            if res and "match" not in res:
                result = "skip" if "skip" in res else "mismatch"
        ga.attribution[e.draft.key] = result

    # Every item non-endorsed (or none at all): decided without the verifier.
    ga.no_call = bool(link.evidence) and all(
        e.answer_status in _NON_ENDORSED for e in link.evidence
    )
    if ga.no_call:
        _question_as_answer(ga, items, turns)
    ga.ambiguous = sorted(set(ga.ambiguous))
    return ga


def _question_as_answer(ga: GroupA, nonendorsed: list, turns: list[IndexedTurn]) -> None:
    for e in nonendorsed:
        seg = [s.turn_index for s in e.draft.segments if 0 <= s.turn_index < len(turns)]
        qs = [i for i in seg if Act.question in turns[i].acts] or seg[:1]
        for q in qs:
            if turns[q].role is None or turns[q].speaker is None:
                ga.role_skipped += 1
                ga.ambiguous.append(q)
        if any(turns[q].role == Role.interviewer and turns[q].speaker is not None for q in qs):
            ga.question_as_answer.append(e.draft.key)
