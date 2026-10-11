import math

import pytest
from link_helpers import VARIANTS, adhd_prep, adhd_turns, claim

from iaudit_backend.link.context import build_link_context, estimate_tokens
from iaudit_backend.models import Turn
from iaudit_backend.prep import PrepResult, index_turns, pair_turns


def prep_of(texts: list[str]):
    turns = [Turn(id=str(i), speaker="ab"[i % 2], text=t) for i, t in enumerate(texts)]
    ts, pairs = pair_turns(index_turns(turns))
    return turns, PrepResult(ts, pairs)


def test_estimate_is_ceil_chars_over_four():
    assert estimate_tokens([Turn(id="1", speaker="a", text="x" * 9)]) == math.ceil(9 / 4)
    assert estimate_tokens([]) == 0
    two = [Turn(id="1", speaker="a", text="x" * 4), Turn(id="2", speaker="b", text="y" * 5)]
    assert estimate_tokens(two) == 3


def test_auto_picks_whole_below_threshold(make_ctx):
    lctx = build_link_context(adhd_turns(), adhd_prep(), make_ctx())
    assert lctx.mode == "whole" and lctx.est_tokens < 1000


def test_auto_boundary_is_strictly_below(make_ctx):
    turns, prep = prep_of(["x" * 40])  # 10 tokens
    below = build_link_context(turns, prep, make_ctx(link_whole_max_tokens=11))
    equal = build_link_context(turns, prep, make_ctx(link_whole_max_tokens=10))
    assert (below.mode, equal.mode) == ("whole", "shortlist")


def test_forced_modes_ignore_size(make_ctx):
    assert (
        build_link_context(adhd_turns(), adhd_prep(), make_ctx(link_mode="shortlist")).mode
        == "shortlist"
    )
    turns, prep = prep_of(["x" * 400_000])
    assert build_link_context(turns, prep, make_ctx(link_mode="whole")).mode == "whole"


def test_whole_mode_selects_every_turn_without_retrieval(make_ctx):
    lctx = build_link_context(adhd_turns(), adhd_prep(), make_ctx(link_mode="whole"))
    sl = lctx.select(claim("anything at all"))
    assert (sl.mode, sl.indices) == ("whole", list(range(26)))


def test_shortlist_mode_selects_subset_with_gold(make_ctx):
    lctx = build_link_context(adhd_turns(), adhd_prep(), make_ctx(link_mode="shortlist"))
    text, gold = VARIANTS["v4"]
    sl = lctx.select(claim(text))
    assert sl.mode == "shortlist" and gold <= set(sl.indices) and len(sl.indices) < 26


def test_empty_shortlist_falls_back_to_whole_under_fallback_cap(make_ctx):
    lctx = build_link_context(adhd_turns(), adhd_prep(), make_ctx(link_mode="shortlist"))
    sl = lctx.select(claim("Zyxwv qqqq wwwww.", subject="Zed"))
    assert sl.mode == "whole" and sl.indices == list(range(26))


def test_empty_shortlist_over_fallback_cap_stays_empty(make_ctx):
    lctx = build_link_context(
        adhd_turns(), adhd_prep(), make_ctx(link_mode="shortlist", link_fallback_max_tokens=10)
    )
    sl = lctx.select(claim("Zyxwv qqqq wwwww.", subject="Zed"))
    assert sl.mode == "empty" and sl.indices == []


def test_context_holds_a_stage_semaphore_of_configured_size(make_ctx):
    lctx = build_link_context(adhd_turns(), adhd_prep(), make_ctx(link_concurrency=3))
    assert lctx.sem._value == 3


@pytest.mark.parametrize("n", [0, 1])
def test_tiny_transcripts(make_ctx, n):
    turns, prep = prep_of(["hello there"] * n)
    lctx = build_link_context(turns, prep, make_ctx())
    assert lctx.mode == "whole" and lctx.select(claim("hello")).indices == list(range(n))
