"""R4: question-answer pairing by `speaker` string only (roles are optional, never used)."""

from dataclasses import replace

from .models import Act, IndexedTurn, QAPair


def pair_turns(turns: list[IndexedTurn]) -> tuple[list[IndexedTurn], list[QAPair]]:
    """Link each question to the turns that respond to it.

    Responses are the following turns by other speakers, up to the questioner's next turn or
    the next question from another speaker. A question directly after Q is both a response to
    Q and the start of its own pair (both links), and ends Q's set.
    """
    responds: dict[int, int] = {}
    pairs: list[QAPair] = []
    for q in turns:
        if Act.question not in q.acts:
            continue
        resp: list[int] = []
        for t in turns[q.index + 1 :]:
            if t.speaker == q.speaker:
                break
            if Act.question in t.acts:
                if t.index == q.index + 1:
                    resp.append(t.index)
                break
            resp.append(t.index)
        if resp:
            pairs.append(QAPair(q.index, tuple(resp)))
            for i in resp:
                responds[i] = q.index
    out = [replace(t, responds_to=responds.get(t.index)) for t in turns]
    return out, pairs
