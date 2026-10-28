"""R1: BM25 shortlist over turns plus question/answer/clarification neighbors. Pure code."""

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from rank_bm25 import BM25Okapi
from rapidfuzz import fuzz

from eaudit.atomize.models import AtomicClaim
from eaudit.config import Settings
from eaudit.prep import Act, PrepResult

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


@runtime_checkable
class Retriever(Protocol):
    """Ranks turns for a claim: (turn_index, positive score), best first, ties by index.

    Lets another retriever (for example an embedding one) be benchmarked without touching
    the linker.
    """

    def rank(self, claim: AtomicClaim) -> list[tuple[int, float]]: ...


def _ordered(scores: dict[int, float]) -> list[tuple[int, float]]:
    return sorted(((i, s) for i, s in scores.items() if s > 0), key=lambda p: (-p[1], p[0]))


class Bm25Retriever:
    """BM25 over every turn. A short reply also carries the question it answers."""

    def __init__(self, prep: PrepResult) -> None:
        turns = prep.turns
        docs = []
        for t in turns:
            toks = tokenize(t.text)
            if t.responds_to is not None and len(toks) <= SHORT_ANSWER_TOKENS:
                toks = toks + tokenize(turns[t.responds_to].text)
            docs.append(toks)
        self._n = len(turns)
        self._bm25 = BM25Okapi(docs) if any(docs) else None

    def scores(self, claim: AtomicClaim) -> list[float]:
        q = tokenize(query_text(claim))
        if self._bm25 is None or not q:
            return [0.0] * self._n
        return [float(s) for s in self._bm25.get_scores(q)]

    def rank(self, claim: AtomicClaim) -> list[tuple[int, float]]:
        return _ordered(dict(enumerate(self.scores(claim))))


FUZZ_MIN = 50  # token_set_ratio below this is noise


class FuzzyRetriever:
    """rapidfuzz token_set_ratio of the proposition against each turn (covers typos)."""

    def __init__(self, prep: PrepResult) -> None:
        self._texts = [t.text for t in prep.turns]

    def rank(self, claim: AtomicClaim) -> list[tuple[int, float]]:
        scores = {
            i: float(r)
            for i, text in enumerate(self._texts)
            if (r := fuzz.token_set_ratio(claim.proposition, text)) >= FUZZ_MIN
        }
        return _ordered(scores)


class FusedRetriever:
    """BM25 and fuzzy rankings fused by reciprocal rank: score = sum of 1 / (k + rank)."""

    def __init__(self, prep: PrepResult, k: int = 60) -> None:
        self._rankers: list[Retriever] = [Bm25Retriever(prep), FuzzyRetriever(prep)]
        self._k = k

    def rank(self, claim: AtomicClaim) -> list[tuple[int, float]]:
        fused: dict[int, float] = {}
        for ranker in self._rankers:
            for pos, (i, _) in enumerate(ranker.rank(claim), 1):
                fused[i] = fused.get(i, 0.0) + 1.0 / (self._k + pos)
        return _ordered(fused)


class TurnIndex:
    """Retrieval index over all turns, built once per request."""

    def __init__(self, prep: PrepResult, retriever: Retriever | None = None) -> None:
        self.prep = prep
        self.turns = prep.turns
        self._pair_of = {p.question_index: p for p in prep.qa_pairs}
        self.retriever: Retriever = retriever or Bm25Retriever(prep)

    def shortlist(self, claim: AtomicClaim, cfg: Settings) -> Shortlist:
        ranked_pairs = self.retriever.rank(claim)
        scores = dict(ranked_pairs)
        ranked = [i for i, _ in ranked_pairs]
        hits = ranked[: cfg.link_top_k]
        if not hits:
            return Shortlist(indices=[], mode="shortlist", scores={})
        positive = set(ranked)
        adds = self._speaker_floor(ranked, hits, cfg)
        anchors = hits + adds
        extras: list[int] = []  # neighbors in priority order

        def add(i: int) -> None:
            if 0 <= i < len(self.turns) and i not in anchors and i not in extras:
                extras.append(i)

        for h in anchors:
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
        for j in self._later_corrections(claim, anchors, cfg):
            add(j)
        keep = extras[: max(0, cfg.link_max_shortlist - len(anchors))]
        chosen = set(anchors) | set(keep)
        for i in range(len(self.turns) - 2):  # fill one-turn gaps
            if i in chosen and i + 2 in chosen:
                chosen.add(i + 1)
        return Shortlist(
            indices=sorted(chosen), mode="shortlist", hits=hits, scores={i: scores[i] for i in hits}
        )

    def _speaker_floor(self, ranked: list[int], hits: list[int], cfg: Settings) -> list[int]:
        """Best-ranked turns of speakers who have a match but fewer than the floor in the top-k."""
        floor, budget = cfg.link_per_speaker_floor, cfg.link_max_speaker_adds
        if floor <= 0 or budget <= 0:
            return []
        have: dict[str, int] = {}
        for h in hits:
            have[self.turns[h].speaker] = have.get(self.turns[h].speaker, 0) + 1
        adds: list[int] = []
        for i in ranked:  # best first, so each speaker's best turns come first
            if len(adds) >= budget:
                break
            sp = self.turns[i].speaker
            if i not in hits and have.get(sp, 0) < floor:
                adds.append(i)
                have[sp] = have.get(sp, 0) + 1
        return adds

    def _later_corrections(
        self, claim: AtomicClaim, anchors: list[int], cfg: Settings
    ) -> list[int]:
        """Later turns (any distance) where an anchor's speaker corrects themselves on the topic."""
        cap = cfg.link_later_correction_cap
        if cap <= 0:
            return []
        query = set(tokenize(query_text(claim)))
        out: list[int] = []
        for h in anchors:
            speaker = self.turns[h].speaker
            for j in range(h + 1, len(self.turns)):
                u = self.turns[j]
                if (
                    u.speaker == speaker
                    and Act.correction in u.acts
                    and j not in out
                    and query & set(tokenize(u.text))
                ):
                    out.append(j)
                    if len(out) >= cap:
                        return out
        return out


def shortlist_only(claim: AtomicClaim, index: TurnIndex, cfg: Settings) -> Shortlist:
    """Pure retrieval, no LLM and no client: lets evaluation measure recall at the shortlist."""
    return index.shortlist(claim, cfg)
