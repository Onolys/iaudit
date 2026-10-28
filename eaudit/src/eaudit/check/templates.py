"""Neutral explanation templates. Slots are code-derived only: scale names, source nouns, counts.

No transcript text, timestamp, speaker id or identity guess ever enters a template (rules 9, 12).
Vocabulary stays fixed: "is not substantiated by the supplied interview", "may differ",
"a reviewer may wish to confirm".
"""

import re
from dataclasses import dataclass

from eaudit.config import Settings
from eaudit.models import ConcernType, Role, Verdict

from .models import Concern

BANNED = re.compile(
    r"fabricat|\blie\b|\blies\b|\blying\b|false claim|dishonest|misconduct|deliberate"
    r"|misrepresent",
    re.IGNORECASE,
)
_MAX_REVISION_WORDS = 40
_TIMESTAMP = re.compile(r"\b\d{1,2}:\d{2}(?::\d{2})?\b|\[\d")
REVISABLE = frozenset(
    {
        ConcernType.frequency_severity_inflation,
        ConcernType.negation_reversal,
        ConcernType.certainty_inflation,
        ConcernType.context_stripping,
        ConcernType.quantity_mismatch,
        ConcernType.opinion_as_fact,
        ConcernType.meaning_shift,
        ConcernType.unsupported_inference,
    }
)

VERDICT_TEXT: dict[Verdict, str] = {
    Verdict.supported: "The supplied interview supports this claim.",
    Verdict.partially_supported: "The supplied interview only partly supports this claim.",
    Verdict.contradicted: "This claim is contradicted by the supplied interview.",
    Verdict.insufficient_evidence: "This claim is not substantiated by the supplied interview.",
    Verdict.out_of_scope: "This statement is outside what the audit checks.",
}
STALLED_TEXT = "This claim could not be checked in this run."


@dataclass(frozen=True)
class Slots:
    source: str = "another speaker"  # "the respondent" | "the informant" | "another speaker"
    turns: int = 0  # number of cited turns


def source_noun(roles: list[Role | None]) -> str:
    kinds = {r for r in roles if r is not None}
    if roles and None not in roles and len(kinds) == 1:
        if kinds == {Role.respondent}:
            return "the respondent"
        if kinds == {Role.informant}:
            return "the informant"
    return "another speaker"


def _passages(n: int) -> str:
    return "a passage" if n == 1 else f"{n} passages"


def concern_text(c: Concern, s: Slots) -> str:
    t = ConcernType
    scale = c.scale or "frequency or severity"
    texts = {
        t.unsupported_claim: (
            "This claim is not substantiated by the supplied interview; a reviewer may wish "
            "to confirm whether the interview covers it."
        ),
        t.contradictory_evidence: (
            f"The supplied interview contains {_passages(s.turns)} from {s.source} that point "
            "the other way; a reviewer may wish to confirm."
        ),
        t.wrong_attribution: (
            "The behavior appears in the interview, but the source, person or entity described "
            "may differ from what the claim states; a reviewer may wish to confirm who or "
            "what it concerns."
        ),
        t.timeframe_mismatch: (
            "The related passage describes a different time period than the claim states, so "
            "it does not substantiate the claim as written."
        ),
        t.negation_reversal: (
            f"The related passage from {s.source} says the opposite of the claim."
        ),
        t.certainty_inflation: (
            "The claim is stated more firmly than the related passage, which is tentative."
        ),
        t.frequency_severity_inflation: (
            f"The claim {c.direction or 'inflates'} the {scale} described by {s.source}; the "
            "stated amount may differ from what the interview supports."
        ),
        t.context_stripping: (
            "The related passage includes a qualifier, reason or limit that the claim leaves out "
            "or broadens."
        ),
        t.question_as_answer: (
            "The related passage is an interviewer question without an answer, so it is not "
            "substantiated by the supplied interview."
        ),
        t.correction_ignored: ("A later passage corrects or changes what the cited passage says."),
        t.conflicting_accounts_flattened: (
            "Speakers give differing accounts, but the claim presents them as agreeing."
        ),
        t.unsupported_causal_link: (
            "The claim states a cause-and-effect link that the supplied interview does not "
            "establish."
        ),
        t.quantity_mismatch: (
            "The claim states an amount, count or value that may differ from the supplied "
            "interview; a reviewer may wish to confirm the figure."
        ),
        t.opinion_as_fact: (
            "The related passage gives this as someone's view or belief, but the claim states "
            "it as fact"
        ),
        t.calculation_error: (
            "The total or result the claim states may differ from the figures the supplied "
            "interview gives; a reviewer may wish to confirm the calculation"
        ),
        t.meaning_shift: (
            "The claim uses a word or action whose meaning may differ from what the related "
            "passage describes; a reviewer may wish to confirm"
        ),
        t.unsupported_inference: (
            "The claim links facts, or generalizes beyond them, in a way the supplied interview "
            "does not establish"
        ),
    }
    return texts[c.type]


def claim_text(verdict: Verdict, concerns: list[Concern]) -> str:
    """One verdict sentence plus the concern type names; the detail lives in each concern."""
    if not concerns:
        return VERDICT_TEXT[verdict]
    names = ", ".join(
        f"{c.type.value} ({c.direction})" if c.direction else c.type.value for c in concerns
    )
    return f"{VERDICT_TEXT[verdict]} Concerns: {names}."


def vet_revision(
    text: str | None, verdict: Verdict, concerns: list[Concern], cfg: Settings
) -> str | None:
    """Keep the verifier's one-sentence revision only when it is safe and relevant."""
    if not cfg.check_suggest_revision or not text:
        return None
    if verdict not in (Verdict.partially_supported, Verdict.contradicted):
        return None
    if not any(c.type in REVISABLE for c in concerns):
        return None
    text = " ".join(text.split())
    if (
        not text
        or _TIMESTAMP.search(text)
        or BANNED.search(text)
        or len(text.split()) > _MAX_REVISION_WORDS
    ):
        return None
    return text
