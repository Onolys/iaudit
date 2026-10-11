"""Stage 0: indexed turns with dialogue acts and question-answer pairs.

Rules decide every act they can. With `prep_llm` on, a cheap-tier call tags the turns the
rules were unsure about; otherwise unsure acts resolve to none and no LLM call is made.
"""

from iaudit_backend.models import Turn
from iaudit_backend.safe_log import log_event

from .llm import tag_unsure
from .models import Act, IndexedTurn, PrepResult, QAPair
from .pairing import pair_turns
from .rules import index_turns, unsure_acts

__all__ = [
    "Act",
    "IndexedTurn",
    "PrepResult",
    "QAPair",
    "index_turns",
    "pair_turns",
    "prep",
    "prep_rules_only",
]


def prep_rules_only(turns: list[Turn]) -> PrepResult:
    """No LLM: the path used when prep runs past its soft timeout."""
    indexed, pairs = pair_turns(index_turns(turns))
    return PrepResult(turns=indexed, qa_pairs=pairs)


async def prep(turns: list[Turn], ctx) -> PrepResult:
    indexed = index_turns(turns)
    degraded = 0
    undecided = 0
    if ctx.settings.prep_llm:
        kinds = unsure_acts(turns, indexed)
        undecided = len(kinds)
        indexed, degraded = await tag_unsure(indexed, kinds, ctx)
    indexed, pairs = pair_turns(indexed)
    log_event(
        "prep",
        request_id=ctx.request_id,
        turns=len(indexed),
        pairs=len(pairs),
        undecided=undecided,
        degraded_chunks=degraded,
    )
    return PrepResult(turns=indexed, qa_pairs=pairs, degraded_chunks=degraded)
