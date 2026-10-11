"""Builders for check tests."""

from link_helpers import adhd_prep, claim  # noqa: F401

from iaudit_backend.assembler.models import EvidenceDraft, ExcerptSegment
from iaudit_backend.link.models import LinkedEvidence, LinkResult


def ev(cid="c0.1", n=1, turn=3, text="Most meetings.", role="supporting", status="n/a",
       lt="quote", premises=(), step=None, turns=None):  # fmt: skip
    segs = (
        [ExcerptSegment(turn_index=t, text=text) for t in (turns or [turn])]
        if lt != "inference"
        else []
    )
    return LinkedEvidence(
        draft=EvidenceDraft(key=f"{cid}:e{n}", role=role, segments=segs),
        link_type=lt,
        premise_keys=list(premises),
        inference_step=step,
        answer_status=status,
    )


def link(*evidence, cid="c0.1", status="ok", reason=None, ambiguous=(), mode="whole"):
    return LinkResult(
        claim_id=cid, status=status, reason=reason, mode=mode, evidence=list(evidence),
        ambiguous_turns=list(ambiguous),
    )  # fmt: skip
