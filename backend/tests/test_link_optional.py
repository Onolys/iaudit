"""04 optional: speaker floor, later correction, RRF fusion, Retriever + shortlist_only, cache."""

import pytest
from link_helpers import VARIANTS, adhd_prep, claim

from iaudit_backend.config import Settings
from iaudit_backend.link import shortlist_only
from iaudit_backend.link.shortlist import (
    Bm25Retriever,
    FusedRetriever,
    Retriever,
    TurnIndex,
)
from iaudit_backend.models import Turn
from iaudit_backend.prep import PrepResult, index_turns, pair_turns


def prep_of(*rows: tuple[str, str]) -> PrepResult:
    turns = [Turn(id=f"t{i}", speaker=s, text=t) for i, (s, t) in enumerate(rows)]
    idx, pairs = pair_turns(index_turns(turns))
    return PrepResult(turns=idx, qa_pairs=pairs)


FILLER = [("pat", f"Keys keys keys number {i} were lost again.") for i in range(10)]
SON = ("son", "She puts the keys down somewhere new each day.")
CLAIM = claim("The patient loses her keys.", subject="patient")


def cfg(**kw) -> Settings:
    return Settings(**kw)


# -- per-speaker floor -----------------------------------------------------------------------


def test_floor_adds_a_speakers_best_turn_when_it_does_not_rank():
    prep = prep_of(*FILLER, SON)
    off = TurnIndex(prep).shortlist(CLAIM, cfg(link_per_speaker_floor=0, link_top_k=4))
    on = TurnIndex(prep).shortlist(CLAIM, cfg(link_per_speaker_floor=1, link_top_k=4))
    assert 10 not in off.indices and 10 in on.indices


def test_floor_respects_the_total_add_cap():
    gap = ("pat", "Nice weather.")
    rows = [*FILLER, ("son", "Keys are lost often."), gap, ("dau", "Her keys go missing."), gap,
            ("mom", "The keys again."), gap, ("dad", "Keys missing.")]  # fmt: skip
    prep = prep_of(*rows)
    s = cfg(link_per_speaker_floor=1, link_max_speaker_adds=2, link_top_k=3, link_max_shortlist=30)
    sl = TurnIndex(prep).shortlist(CLAIM, s)
    speakers = {10, 12, 14, 16}  # one matching turn per other speaker
    assert len(speakers & set(sl.indices)) == 2


def test_floor_ignores_speakers_with_no_positive_score_turn():
    prep = prep_of(*FILLER, ("bystander", "Nice weather."))
    sl = TurnIndex(prep).shortlist(CLAIM, cfg(link_per_speaker_floor=2, link_top_k=4))
    assert 10 not in sl.indices


def test_floor_default_is_on_and_zero_disables():
    assert Settings().link_per_speaker_floor == 2 and Settings().link_max_speaker_adds == 4
    prep = prep_of(*FILLER, SON)
    sl = TurnIndex(prep).shortlist(CLAIM, cfg(link_per_speaker_floor=0, link_top_k=4))
    assert 10 not in sl.indices


# -- later correction ------------------------------------------------------------------------


LATE = [
    ("pat", "I lose my keys every single day."),
    *[("doc", "Mm-hm, noted.") if i % 2 == 0 else ("pat", "Weather is fine.") for i in range(8)],
    ("pat", "Actually, about the keys, it is only monthly."),
]


def test_later_correction_by_the_same_speaker_is_pulled_in():
    prep = prep_of(*LATE)
    on = TurnIndex(prep).shortlist(CLAIM, cfg(link_top_k=1, link_per_speaker_floor=0))
    off = TurnIndex(prep).shortlist(
        CLAIM, cfg(link_top_k=1, link_per_speaker_floor=0, link_later_correction_cap=0)
    )
    assert 9 in on.indices and 9 not in off.indices


def test_later_correction_needs_a_shared_query_token():
    rows = [*LATE[:-1], ("pat", "Actually, the dog is fine.")]
    sl = TurnIndex(prep_of(*rows)).shortlist(CLAIM, cfg(link_top_k=1, link_per_speaker_floor=0))
    assert 9 not in sl.indices


def test_later_correction_is_capped():
    rows = [("pat", "I lose my keys daily.")] + [("doc", "ok")] * 6
    rows += [("pat", f"Actually the keys thing {i}.") for i in range(6)]
    sl = TurnIndex(prep_of(*rows)).shortlist(
        CLAIM,
        cfg(
            link_top_k=1,
            link_per_speaker_floor=0,
            link_correction_window=0,
            link_later_correction_cap=3,
        ),
    )
    assert len([i for i in sl.indices if i >= 7]) <= 3 + 1  # cap, plus at most one gap fill


# -- Retriever protocol, fusion, shortlist_only ----------------------------------------------


def test_bm25_retriever_satisfies_the_protocol():
    r = Bm25Retriever(adhd_prep())
    assert isinstance(r, Retriever)
    ranked = r.rank(claim(VARIANTS["v1"][0]))
    assert ranked and ranked == sorted(ranked, key=lambda p: (-p[1], p[0]))
    assert all(s > 0 for _, s in ranked) and 3 in {i for i, _ in ranked[:3]}


def test_a_custom_retriever_drives_the_shortlist():
    class Fixed:
        def rank(self, claim):
            return [(2, 1.0)]

    prep = adhd_prep()
    sl = TurnIndex(prep, retriever=Fixed()).shortlist(
        claim("anything"), cfg(link_per_speaker_floor=0)
    )
    assert sl.hits == [2]


def test_fusion_finds_a_fuzzy_match_that_bm25_misses():
    prep = prep_of(("pat", "Zzyzx quuxington fnord."), ("doc", "Anything else?"))
    c = claim("Zzyzx quuxingtonn fnord.", subject="x")  # typo: no BM25 token overlap
    assert TurnIndex(prep).shortlist(c, cfg(link_per_speaker_floor=0)).indices == []
    fused = TurnIndex(prep, retriever=FusedRetriever(prep)).shortlist(
        c, cfg(link_per_speaker_floor=0)
    )
    assert 0 in fused.hits


def test_fusion_uses_reciprocal_rank():
    prep = adhd_prep()
    c = claim(VARIANTS["v1"][0])
    ranked = FusedRetriever(prep, k=60).rank(c)
    assert ranked and ranked == sorted(ranked, key=lambda p: (-p[1], p[0]))
    assert max(s for _, s in ranked) <= 2 / 61 + 1e-9  # two rankers, rank 1 each at most


@pytest.mark.parametrize("variant", sorted(VARIANTS))
def test_fusion_keeps_every_gold_turn(variant):
    text, gold = VARIANTS[variant]
    prep = adhd_prep()
    sl = TurnIndex(prep, retriever=FusedRetriever(prep)).shortlist(claim(text), cfg())
    assert gold <= set(sl.indices)


def test_context_uses_fusion_only_when_enabled(make_ctx):
    from iaudit_backend.link import build_link_context

    prep = adhd_prep()
    turns = [Turn(id=t.id, speaker=t.speaker, text=t.text) for t in prep.turns]
    off = build_link_context(turns, prep, make_ctx())
    on = build_link_context(turns, prep, make_ctx(link_fusion=True))
    assert isinstance(off.index.retriever, Bm25Retriever)
    assert isinstance(on.index.retriever, FusedRetriever)


def test_shortlist_only_needs_no_client_and_matches_the_index():
    prep = adhd_prep()
    c = claim(VARIANTS["v4"][0])
    idx = TurnIndex(prep)
    sl = shortlist_only(c, idx, cfg())
    assert sl.indices == idx.shortlist(c, cfg()).indices and {12, 13} <= set(sl.indices)


# -- cache layout ----------------------------------------------------------------------------


async def _requests(make_ctx, mode, **kw):
    from atomize_helpers import raw  # noqa: F401
    from link_helpers import adhd_turns

    from iaudit_backend.link import build_link_context, link_one
    from iaudit_backend.link.models import LinkerOutput
    from iaudit_backend.llm import LLMResult, StubClient

    seen = []

    class Spy(StubClient):
        async def complete_json(self, req, metrics=None):
            seen.append(req)
            return LLMResult(parsed=LinkerOutput(items=[]), model="s")

    ctx = make_ctx(llm=Spy(), link_mode=mode, **kw)
    lctx = build_link_context(adhd_turns(), adhd_prep(), ctx)
    await link_one(claim(VARIANTS["v1"][0]), lctx, ctx)
    return seen[0]


async def test_default_layout_is_one_cache_prefix(make_ctx):
    r = await _requests(make_ctx, "whole")
    assert r.cache_prefix and r.cache_prefixes == []


async def test_whole_mode_two_breakpoints_transcript_then_stage_block(make_ctx):
    from iaudit_backend.link.prompt import stage_block

    r = await _requests(make_ctx, "whole", link_cache_breakpoints=2)
    assert len(r.cache_prefixes) == 2 and r.cache_prefix is None
    assert "# Transcript" in r.cache_prefixes[0] and r.cache_prefixes[1] == stage_block()
    assert VARIANTS["v1"][0] not in "".join(r.cache_prefixes) and VARIANTS["v1"][0] in r.user


async def test_shortlist_mode_keeps_a_single_breakpoint(make_ctx):
    r = await _requests(make_ctx, "shortlist", link_cache_breakpoints=2)
    assert len(r.cache_prefixes) <= 1
