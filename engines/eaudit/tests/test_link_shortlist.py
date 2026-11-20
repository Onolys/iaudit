import pytest
from link_helpers import VARIANTS, adhd_prep, claim

from eaudit.config import Settings
from eaudit.link.shortlist import TurnIndex, query_text
from eaudit.link.tokenize import stem, tokenize
from eaudit.models import Turn
from eaudit.prep import PrepResult, index_turns, pair_turns


def test_stemmer_suffixes_and_min_stem():
    assert [stem(w) for w in ["forgets", "losing", "missed", "quickly", "studies"]] == [
        "forget", "los", "miss", "quick", "study",
    ]  # fmt: skip
    assert stem("is") == "is" and stem("bus") == "bus" and stem("red") == "red"  # min stem 3
    assert stem("alex's") == "alex"


def test_prefix_channel_joins_morphological_variants():
    a, b = set(tokenize("He forgets things")), set(tokenize("She is forgetful"))
    assert "p:forge" in a & b
    assert set(tokenize("weekly")) & set(tokenize("a week"))  # stem 'week'


def test_stopwords_dropped_but_negators_and_numbers_kept():
    toks = tokenize("The patient did not take 3 pills, never")
    assert "the" not in toks and "did" not in toks
    assert "not" in toks and "never" in toks and "3" in toks


def test_tokenize_is_nfkc_lowercase_and_handles_empty():
    assert tokenize("ＦＯＲＧＥＴ") == tokenize("forget")
    assert tokenize("") == [] and tokenize("... ,,") == []


@pytest.mark.parametrize("roles", [False, True])
@pytest.mark.parametrize("variant", sorted(VARIANTS))
def test_shortlist_contains_every_gold_turn(variant, roles):
    text, gold = VARIANTS[variant]
    sl = TurnIndex(adhd_prep(roles)).shortlist(claim(text), Settings())
    assert gold <= set(sl.indices), (variant, sl.indices)
    assert sl.mode == "shortlist" and sl.indices == sorted(set(sl.indices))


def test_short_answers_inherit_the_paired_question_tokens():
    idx = TurnIndex(adhd_prep())
    # "Hm." (13) shares no word with the claim but answers "easily distracted" (12)
    sl = idx.shortlist(claim("He is easily distracted by his surroundings."), Settings())
    assert 13 in sl.indices and sl.scores.get(13, 0) > 0


def test_responding_hit_pulls_in_its_question():
    sl = TurnIndex(adhd_prep()).shortlist(
        claim("He makes careless mistakes in reports."), Settings()
    )
    assert 5 in sl.hits and 4 in sl.indices  # the question before the answer


def test_question_hit_pulls_in_its_responses():
    prep = adhd_prep()
    sl = TurnIndex(prep).shortlist(
        claim("Is he easily distracted by things around him."), Settings()
    )
    assert 12 in sl.hits and 13 in sl.indices


def test_clarification_window_adds_corrections_and_same_speaker_hits():
    sl = TurnIndex(adhd_prep()).shortlist(claim("He has a half-painted bathroom."), Settings())
    assert 11 in sl.hits  # turn 11 itself holds the 'Actually' correction


def test_hits_are_capped_at_top_k_and_positive_only():
    cfg = Settings(link_top_k=2)
    sl = TurnIndex(adhd_prep()).shortlist(claim("He forgets groceries and errands."), cfg)
    assert len(sl.hits) <= 2 and all(sl.scores[i] > 0 for i in sl.hits)


def test_cap_never_drops_bm25_hits_and_drops_neighbors_first():
    cfg = Settings(link_max_shortlist=4)
    sl = TurnIndex(adhd_prep()).shortlist(claim("He forgets groceries and errands."), cfg)
    assert set(sl.hits) <= set(sl.indices)
    small = TurnIndex(adhd_prep()).shortlist(claim("He forgets groceries and errands."), Settings())
    assert len(sl.indices) <= len(small.indices)


def test_one_turn_gaps_are_filled():
    turns = [Turn(id=str(i), speaker="a" if i % 2 == 0 else "b", text=t) for i, t in enumerate(
        ["apple pie recipe", "unrelated words here", "apple pie again", "x", "y"]
    )]  # fmt: skip
    ts, pairs = pair_turns(index_turns(turns))
    sl = TurnIndex(PrepResult(ts, pairs)).shortlist(claim("apple pie"), Settings())
    assert {0, 1, 2} <= set(sl.indices)


def test_no_positive_score_gives_empty_shortlist():
    sl = TurnIndex(adhd_prep()).shortlist(claim("Zyxwv qqqq wwwww.", subject="Zed"), Settings())
    assert sl.indices == [] and sl.hits == []


def test_empty_transcript_and_empty_query_do_not_crash():
    idx = TurnIndex(PrepResult([], []))
    assert idx.shortlist(claim("anything here", subject=""), Settings()).indices == []
    assert (
        TurnIndex(adhd_prep()).shortlist(claim("the of and", subject=""), Settings()).indices == []
    )


def test_query_text_dedups_and_includes_slots():
    c = claim("Alex naps daily.", segments=["Alex naps daily."], quantities=["daily", "daily"])
    q = query_text(c)
    assert q.count("Alex naps daily.") == 1 and "daily" in q and "Alex" in q
