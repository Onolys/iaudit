"""R2: choose whole-transcript or shortlist mode once per request."""

import asyncio
import math
from dataclasses import dataclass, field

from iaudit_backend.atomize.models import AtomicClaim
from iaudit_backend.models import Turn
from iaudit_backend.prep import PrepResult

from .shortlist import FusedRetriever, Shortlist, TurnIndex


def estimate_tokens(turns: list[Turn]) -> int:
    """No tokenizer dependency: ceil(total chars / 4)."""
    return math.ceil(sum(len(t.text) for t in turns) / 4)


@dataclass
class LinkContext:
    turns: list[Turn]
    prep: PrepResult
    index: TurnIndex
    mode: str  # whole | shortlist
    est_tokens: int
    ctx: object  # RequestContext
    sem: asyncio.Semaphore = field(default_factory=lambda: asyncio.Semaphore(20))

    def select(self, claim: AtomicClaim) -> Shortlist:
        cfg = self.ctx.settings
        everything = list(range(len(self.turns)))
        if self.mode == "whole":
            return Shortlist(indices=everything, mode="whole")
        sl = self.index.shortlist(claim, cfg)
        if sl.indices:
            return sl
        if self.est_tokens < cfg.link_fallback_max_tokens:
            return Shortlist(indices=everything, mode="whole")
        return Shortlist(indices=[], mode="empty")


def choose_mode(est_tokens: int, cfg) -> str:
    """whole | shortlist, from the transcript size and `link_mode`."""
    if cfg.link_mode == "auto":
        return "whole" if est_tokens < cfg.link_whole_max_tokens else "shortlist"
    return cfg.link_mode


def build_link_context(turns: list[Turn], prep: PrepResult, ctx) -> LinkContext:
    cfg = ctx.settings
    est = estimate_tokens(turns)
    mode = choose_mode(est, cfg)
    return LinkContext(
        turns=turns,
        prep=prep,
        index=TurnIndex(prep, FusedRetriever(prep, cfg.link_rrf_k) if cfg.link_fusion else None),
        mode=mode,
        est_tokens=est,
        ctx=ctx,
        sem=asyncio.Semaphore(cfg.link_concurrency),
    )
