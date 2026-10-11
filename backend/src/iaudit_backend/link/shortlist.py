"""R1: BM25 shortlist over turns plus question/answer/clarification neighbors. Pure code."""

from dataclasses import dataclass, field

from rank_bm25 import BM25Okapi

from iaudit_backend.atomize.models import AtomicClaim
from iaudit_backend.config import Settings
from iaudit_backend.prep import Act, PrepResult

from .tokenize import tokenize

SHORT_ANSWER_TOKENS = 12


@dataclass
class Shortlist:
    indices: list[int] = field(default_factory=list)
    mode: str = "shortlist"
    hits: list[int] = field(default_factory=list)  # BM25 hits, best first
    scores: dict[int, float] = field(default_factory=dict)


def query_text(claim: AtomicClaim) -> str:
    parts = [claim.proposition, *claim.segments, claim.subject_text]
    parts += [q.raw for q in claim.quantities]
    seen: list[str] = []
    for p in parts:
        if p and p not in seen:
            seen.append(p)
    return " ".join(seen)


class TurnIndex:
    """BM25 index over all turns, built once per request."""

    def __init__(self, prep: PrepResult) -> None:
        self.prep = prep
        self.turns = prep.turns
        self._pair_of = {p.question_index: p for p in prep.qa_pairs}
        docs = []
        for t in self.turns:
            toks = tokenize(t.text)
            if t.responds_to is not None and len(toks) <= SHORT_ANSWER_TOKENS:
                toks = toks + tokenize(self.turns[t.responds_to].text)
            docs.append(toks)
        self._bm25 = BM25Okapi(docs) if any(docs) else None

    def scores(self, claim: AtomicClaim) -> list[float]:
        q = tokenize(query_text(claim))
        if self._bm25 is None or not q:
            return [0.0] * len(self.turns)
        return [float(s) for s in self._bm25.get_scores(q)]

    def shortlist(self, claim: AtomicClaim, cfg: Settings) -> Shortlist:
        scores = self.scores(claim)
        ranked = sorted((i for i, s in enumerate(scores) if s > 0), key=lambda i: (-scores[i], i))
        hits = ranked[: cfg.link_top_k]
        if not hits:
            return Shortlist(indices=[], mode="shortlist", scores={})
        positive = {i for i, s in enumerate(scores) if s > 0}
        extras: list[int] = []  # neighbors in priority order

        def add(i: int) -> None:
            if 0 <= i < len(self.turns) and i not in hits and i not in extras:
                extras.append(i)

        for h in hits:
            t = self.turns[h]
            if t.responds_to is not None:
                add(t.responds_to)
                for r in self._pair_of[t.responds_to].response_indices:
                    add(r)
            if Act.question in t.acts and h in self._pair_of:
                for r in self._pair_of[h].response_indices[:3]:
                    add(r)
            for j in range(h + 1, min(h + 1 + cfg.link_correction_window, len(self.turns))):
                u = self.turns[j]
                if Act.correction in u.acts or (u.speaker == t.speaker and j in positive):
                    add(j)
        keep = extras[: max(0, cfg.link_max_shortlist - len(hits))]
        chosen = set(hits) | set(keep)
        for i in range(len(self.turns) - 2):  # fill one-turn gaps
            if i in chosen and i + 2 in chosen:
                chosen.add(i + 1)
        return Shortlist(
            indices=sorted(chosen), mode="shortlist", hits=hits, scores={i: scores[i] for i in hits}
        )
