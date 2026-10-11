import pytest

from iaudit_backend.scales import (
    FrequencyBucket as F,
)
from iaudit_backend.scales import (
    SeverityBucket as S,
)
from iaudit_backend.scales import (
    bucket_from_rate,
    lexicon_bucket,
    parse_rate,
    resolve_quantity,
    step_diff,
)


def test_bucket_values():
    assert [int(b) for b in F] == [0, 1, 2, 3, 4, 5]
    assert [int(b) for b in S] == [0, 1, 2, 3, 4]
    assert [b.name for b in F] == ["never", "rarely", "sometimes", "often", "most", "always"]
    assert [b.name for b in S] == ["none", "mild", "moderate", "severe", "inability"]


@pytest.mark.parametrize(
    "rate,bucket",
    [
        (0, F.never),
        (0.05, F.rarely),
        (0.19, F.rarely),
        (0.2, F.sometimes),
        (0.99, F.sometimes),
        (1, F.often),
        (3.99, F.often),
        (4, F.most),
        (6.99, F.most),
        (7, F.always),
        (21, F.always),
    ],
)
def test_bucket_from_rate_boundaries(rate, bucket):
    assert bucket_from_rate(rate) == bucket


@pytest.mark.parametrize(
    "text,rate",
    [
        ("three or four times a week", 3.5),
        ("3 to 4 times a week", 3.5),
        ("3-4 times per week", 3.5),
        ("twice a month", 2 / (52 / 12)),
        ("once a month", 1 / (52 / 12)),
        ("once a week", 1.0),
        ("twice a week", 2.0),
        ("every day", 7.0),
        ("daily", 7.0),
        ("weekly", 1.0),
        ("monthly", 1 / (52 / 12)),
        ("about 10 times a year", 10 / 52),
        ("five times a day", 35.0),
        ("maybe once a month, if that", 1 / (52 / 12)),
    ],
)
def test_parse_rate(text, rate):
    assert parse_rate(text) == pytest.approx(rate, rel=1e-6)


@pytest.mark.parametrize("text", ["most meetings", "constantly", "sometimes", "poor", ""])
def test_parse_rate_none_for_relative_words(text):
    assert parse_rate(text) is None


def test_spec_examples():
    assert round(parse_rate("twice a month"), 2) == 0.46
    assert bucket_from_rate(parse_rate("three or four times a week")) == F.often
    assert bucket_from_rate(parse_rate("twice a month")) == F.sometimes
    assert bucket_from_rate(parse_rate("every day")) == F.always


@pytest.mark.parametrize(
    "text,bucket",
    [
        ("never", F.never),
        ("rarely", F.rarely),
        ("hardly ever", F.rarely),
        ("almost never", F.rarely),
        ("sometimes", F.sometimes),
        ("now and then", F.sometimes),
        ("often", F.often),
        ("frequently", F.often),
        ("most meetings", F.most),
        ("most days", F.most),
        ("usually", F.most),
        ("always", F.always),
        ("every time", F.always),
        ("constantly", F.always),
        ("every meeting", F.always),
    ],
)
def test_frequency_lexicon(text, bucket):
    assert lexicon_bucket(text, "frequency") == bucket


@pytest.mark.parametrize(
    "text,bucket",
    [
        ("no difficulty", S.none),
        ("slight trouble", S.mild),
        ("a little", S.mild),
        ("some difficulty", S.mild),
        ("moderate", S.moderate),
        ("fair", S.moderate),
        ("considerable", S.moderate),
        ("poor", S.severe),
        ("marked impairment", S.severe),
        ("significant", S.severe),
        ("a lot", S.severe),
        ("unable", S.inability),
        ("can't", S.inability),
        ("completely", S.inability),
    ],
)
def test_severity_lexicon(text, bucket):
    assert lexicon_bucket(text, "severity") == bucket


def test_lexicon_unknown_is_none_and_case_insensitive():
    assert lexicon_bucket("blue", "frequency") is None
    assert lexicon_bucket("USUALLY", "frequency") == F.most
    assert lexicon_bucket("Poor", "severity") == S.severe


def test_longest_phrase_wins():
    assert lexicon_bucket("almost never", "frequency") == F.rarely  # not "never"


def test_resolve_quantity_code_beats_llm_when_numeric():
    q = resolve_quantity("frequency", "three or four times a week", llm_bucket=F.always)
    assert q.bucket == F.often and q.rate_per_week == 3.5


def test_resolve_quantity_relative_keeps_rate_none_and_beats_llm_with_lexicon():
    q = resolve_quantity("frequency", "most meetings", llm_bucket=F.often)
    assert q.bucket == F.most and q.rate_per_week is None


def test_resolve_quantity_falls_back_to_llm_bucket():
    q = resolve_quantity("frequency", "off and on", llm_bucket=F.sometimes)
    assert q.bucket == F.sometimes
    assert resolve_quantity("frequency", "off and on", llm_bucket=None).bucket is None
    assert resolve_quantity("severity", "hard going", llm_bucket=S.moderate).bucket == S.moderate


def test_step_diff_signs_both_directions():
    assert step_diff(S.mild, S.severe) == -2  # "some difficulty" vs "poor": claim understates
    assert step_diff(S.severe, S.mild) == 2  # claim stronger
    assert step_diff(F.always, F.most) == 1
    assert step_diff(F.often, F.often) == 0
    assert step_diff(F.most, F.always) == -1


def test_step_diff_rejects_mixed_kinds():
    with pytest.raises(TypeError):
        step_diff(F.often, S.mild)
