import pytest

from iaudit_backend.assembler.locate import locate
from iaudit_backend.config import Settings

CFG = Settings()


def sl(text, m):
    return text[m.start : m.end]


def test_exact_match():
    t = "She forgot her medication twice last month."
    m = locate(t, "forgot her medication", None, CFG)
    assert (m.tier, m.score) == ("exact", 100)
    assert sl(t, m) == "forgot her medication"


def test_no_match_returns_none():
    assert locate("hello world", "completely unrelated sentence", None, CFG) is None
    assert locate("hello", "   ", None, CFG) is None


def test_exact_result_is_trimmed():
    t = "a  hello world  b"
    m = locate(t, " hello world ", None, CFG)
    assert sl(t, m) == "hello world"


def test_normalized_case_whitespace_curly_quotes():
    t = "I don’t   lose my KEYS."
    m = locate(t, "don't lose my keys", None, CFG)
    assert m.tier == "normalized"
    assert sl(t, m) == "don’t   lose my KEYS"


def test_normalized_dashes_and_zero_width():
    t = "it was a well—known​ fact"
    m = locate(t, "well-known fact", None, CFG)
    assert m.tier == "normalized"
    assert sl(t, m).startswith("well") and sl(t, m).endswith("fact")


def test_length_changing_normalization_sharp_s():
    t = "Die Straße ist lang"
    m = locate(t, "STRASSE ist", None, CFG)
    assert m.tier == "normalized"
    assert sl(t, m) == "Straße ist"


def test_length_changing_normalization_ligature():
    t = "the oﬃce was quiet today"
    m = locate(t, "office was quiet", None, CFG)
    assert sl(t, m) == "oﬃce was quiet"


def test_multiple_spaces_and_newlines():
    t = "one\n\n  two   three"
    m = locate(t, "one two three", None, CFG)
    assert m.tier == "normalized" and (m.start, m.end) == (0, len(t))


def test_emoji_keeps_code_point_offsets():
    t = "hi \U0001f44d\U0001f44d then she left"
    m = locate(t, "then she left", None, CFG)
    assert m.start == 6 and m.end == len(t)


def test_crlf_counts_two_code_points():
    t = "a\r\nb target text"
    m = locate(t, "target text", None, CFG)
    assert m.start == 5


def test_repeated_phrase_prefers_hint_then_first():
    t = "no way. then no way. finally no way."
    assert locate(t, "no way", None, CFG).start == 0
    m = locate(t, "no way", 30, CFG)
    assert m.start == 29
    assert m.occurrences == 3
    assert locate(t, "no way", 9, CFG).start == 13


def test_fuzzy_accepts_typo():
    t = "Caregiver: She forgot her medication twice last month. Moving on."
    m = locate(t, "She forgot her medicaton twice last month", None, CFG)
    assert m.tier == "fuzzy" and m.score >= 90
    assert sl(t, m).startswith("She forgot") and sl(t, m).endswith("month")


def test_fuzzy_rejects_once_vs_twice():
    t = "She forgot her medication twice last month."
    assert locate(t, "She forgot her medication once last month", None, CFG) is None


def test_fuzzy_rejects_dropped_negator():
    t = "The patient did not take the medication yesterday."
    assert locate(t, "The patient did take the medicaton yesterday", None, CFG) is None


def test_fuzzy_rejects_added_negator():
    t = "The patient did take the medication yesterday."
    assert locate(t, "The patient did not take the medicaton yesterday", None, CFG) is None


def test_fuzzy_rejects_short_needle():
    assert locate("abcdefghij klm", "abcdefghjk", None, CFG) is None


def test_fuzzy_digit_guard():
    t = "She missed 3 appointments in the last year."
    assert locate(t, "She missed 4 appointmnts in the last year", None, CFG) is None


def test_ellipsis_fragments_in_order():
    t = "I missed one last year, which was odd, when I was traveling."
    m = locate(t, "I missed one ... when I was traveling", None, CFG)
    assert sl(t, m) == t[:-1]


@pytest.mark.parametrize("ell", ["...", "[…]", "…"])
def test_ellipsis_variants(ell):
    t = "alpha beta gamma delta epsilon"
    m = locate(t, f"alpha beta {ell} delta epsilon", None, CFG)
    assert sl(t, m) == t


def test_ellipsis_out_of_order_fails():
    t = "alpha beta gamma delta epsilon"
    assert locate(t, "delta epsilon ... alpha beta", None, CFG) is None


def test_ellipsis_hull_too_large_rejected():
    t = "start here " + "filler " * 60 + "end there"
    assert locate(t, "start here ... end there", None, CFG) is None


def test_start_and_end_are_never_inside_whitespace():
    t = "x   spaced   out   y"
    m = locate(t, "spaced out", None, CFG)
    assert not t[m.start].isspace() and not t[m.end - 1].isspace()


def test_verbatim_quote_containing_ellipsis_is_found_whole():
    t = "In the morning, when I get to my desk at the office, I... I just forget what I was doing."
    q = "I... I just forget what I was doing."
    m = locate(t, q, None, CFG)
    assert m is not None and (m.tier, m.start) == ("exact", 53)
    assert sl(t, m) == q
