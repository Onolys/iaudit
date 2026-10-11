"""Stage 0 output: indexed turns with dialogue acts and question-answer pairs."""

from dataclasses import dataclass, field, replace
from enum import StrEnum

from iaudit_backend.models import Role


class Act(StrEnum):
    question = "question"
    answer = "answer"
    backchannel = "backchannel"
    hypothetical = "hypothetical"
    correction = "correction"


@dataclass(frozen=True)
class IndexedTurn:
    index: int  # array position; this is the contract span index
    id: str
    speaker: str
    role: Role | None  # copied, never inferred
    text: str
    length: int  # len(text), code points
    acts: frozenset[Act] = frozenset()
    act_source: str = "rule"  # rule | llm | rule_fallback
    responds_to: int | None = None

    def with_responds_to(self, q: int) -> "IndexedTurn":
        return replace(self, responds_to=q)


@dataclass(frozen=True)
class QAPair:
    question_index: int
    response_indices: tuple[int, ...]


@dataclass
class PrepResult:
    turns: list[IndexedTurn] = field(default_factory=list)
    qa_pairs: list[QAPair] = field(default_factory=list)
    degraded_chunks: int = 0  # LLM tagging chunks that fell back to rules
