"""Stage 0: indexed turns with dialogue acts and question-answer pairs (rules only in core)."""

from .models import Act, IndexedTurn, PrepResult, QAPair
from .rules import index_turns

__all__ = ["Act", "IndexedTurn", "PrepResult", "QAPair", "index_turns"]
