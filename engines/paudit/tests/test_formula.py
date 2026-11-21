import pytest

from paudit.formula import FormulaError, check, evaluate, label_for, names

pytestmark = pytest.mark.unit

# The four MITI summary formulas live in tests only (src stays protocol-agnostic).
V = {"cct": 4, "sst": 3, "cr": 6, "sr": 2, "question": 4,
     "seek_collab": 1, "affirm": 2, "emphasize_autonomy": 0}


def test_four_miti_formulas():
    assert evaluate("(cct+sst)/2", V) == 3.5
    assert evaluate("cr/(sr+cr)", V) == 0.75
    assert evaluate("(sr+cr)/question", V) == 2.0
    assert evaluate("seek_collab+affirm+emphasize_autonomy", V) == 3.0


def test_arithmetic_and_precedence():
    assert evaluate("1 + 2 * 3 - -4 / 2", {}) == 9.0
    assert evaluate("(1+2)*3", {}) == 9.0
    assert isinstance(evaluate("2", {}), float)


def test_div_by_zero_is_none():
    assert evaluate("cr/(sr+cr)", {"cr": 0, "sr": 0}) is None
    assert evaluate("1/0", {}) is None


def test_missing_or_none_value_is_none():
    assert evaluate("a+b", {"a": 1}) is None
    assert evaluate("a+b", {"a": 1, "b": None}) is None


@pytest.mark.parametrize("expr", [
    "abs(a)", "a.real", "a if b else c", "a ** 2", "a % 2", "'x'", "True", "None",
    "[a]", "a < b", "a and b", "lambda: 1", "__import__('os')", "a[0]", "a//b", "1j", "",
    "a +",
])
def test_rejects_non_arithmetic(expr):
    with pytest.raises(FormulaError):
        check(expr)
    with pytest.raises(FormulaError):
        evaluate(expr, {"a": 1, "b": 2, "c": 3})


def test_check_returns_names_and_matches_names():
    assert check("(a+b)/c") == {"a", "b", "c"} == names("(a+b)/c")


def test_label_higher_better_boundaries():
    ref = {"fair": 0.4, "good": 0.5, "direction": "higher_better"}
    assert label_for(0.5, ref) == "good"
    assert label_for(0.45, ref) == "fair"
    assert label_for(0.4, ref) == "fair"
    assert label_for(0.39, ref) == "below_fair"
    assert label_for(None, ref) is None
    assert label_for(0.5, {"fair": 0.4, "good": 0.5}) == "good"  # default direction


def test_label_lower_better_boundaries():
    ref = {"fair": 10, "good": 5, "direction": "lower_better"}
    assert label_for(5, ref) == "good"
    assert label_for(7, ref) == "fair"
    assert label_for(10, ref) == "fair"
    assert label_for(10.1, ref) == "below_fair"
