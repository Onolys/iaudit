"""Stage 0: indexed turns with dialogue acts and question-answer pairs (rules only in core)."""

from iaudit_backend.models import Turn
from iaudit_backend.safe_log import log_event

from .models import Act, IndexedTurn, PrepResult, QAPair
from .pairing import pair_turns
from .rules import index_turns

__all__ = ["Act", "IndexedTurn", "PrepResult", "QAPair", "index_turns", "pair_turns", "prep"]


async def prep(turns: list[Turn], ctx) -> PrepResult:
    """Rules-only prep: zero LLM calls (the optional LLM tagging is gated)."""
    indexed, pairs = pair_turns(index_turns(turns))
    log_event("prep", request_id=ctx.request_id, turns=len(indexed), pairs=len(pairs))
    return PrepResult(turns=indexed, qa_pairs=pairs)
