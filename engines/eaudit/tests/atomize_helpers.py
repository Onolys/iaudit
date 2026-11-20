"""Shared builders for atomizer tests."""

from pathlib import Path

from eaudit.atomize.prompt import Speaker
from eaudit.models import AuditRequest, Section
from eval.adhd import faithful_request

FIXTURES = Path(__file__).parent / "fixtures" / "llm"
ROSTER = [Speaker("clinician1", "interviewer"), Speaker("alex1", "respondent")]


def adhd_section() -> Section:
    return AuditRequest.model_validate(faithful_request()).assessment[0]


def raw(**over):
    base = {
        "ref": "a",
        "segments": ["Alex forgets"],
        "proposition": "Alex forgets.",
        "scope": "in_scope",
        "oos_category": None,
        "subject_text": "Alex",
        "subject_speaker": "alex1",
        "reported_by": [{"source": "self", "speaker": "alex1"}],
        "polarity": "affirmed",
        "quantities": [],
        "timeframe": "current",
        "timeframe_explicit": False,
        "hedged": False,
    }
    base.update(over)
    return base
