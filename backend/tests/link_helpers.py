"""Builders for link tests: ADHD prep output and claims."""

from atomize_helpers import raw  # noqa: F401

from eval.adhd import load_spec
from iaudit_backend.atomize.models import AtomicClaim
from iaudit_backend.models import Turn
from iaudit_backend.prep import index_turns, pair_turns


def adhd_turns(roles: bool = False) -> list[Turn]:
    drop = () if roles else ("role",)
    return [
        Turn.model_validate({k: v for k, v in t.items() if k not in drop})
        for t in load_spec()["transcript"]
    ]


def adhd_prep(roles: bool = False):
    from iaudit_backend.prep import PrepResult

    turns, pairs = pair_turns(index_turns(adhd_turns(roles)))
    return PrepResult(turns=turns, qa_pairs=pairs)


def claim(proposition: str, *, cid="c0.1", subject="Alex", quantities=(), segments=None, **kw):
    data = {
        "id": cid,
        "section_index": 0,
        "segments": segments or [proposition.rstrip(".")],
        "proposition": proposition,
        "scope": "in_scope",
        "subject_text": subject,
        "reported_by": [{"source": "unspecified", "speaker": None}],
        "polarity": "affirmed",
        "quantities": [
            r if isinstance(r, dict) else {"kind": "frequency", "raw": r} for r in quantities
        ],
        "timeframe": "current",
        "timeframe_explicit": False,
        "hedged": False,
    }
    data.update(kw)
    return AtomicClaim.model_validate(data)


VARIANTS = {
    "v1": ("Alex loses attention in every meeting, several times a day.", {3}),
    "v2": ("He makes frequent careless mistakes in reports.", {5}),
    "v4": ("He is easily distracted by his surroundings.", {12, 13}),
    "v5": ("He currently forgets work assignments weekly.", {17}),
    "v6": ("Both Alex and his partner agree he forgets errands about twice a month.", {19}),
    "v7": ("The unfinished bathroom shows his difficulty completing tasks.", {11}),
    "v8": ("His distractibility caused a negative performance review.", {25}),
}
