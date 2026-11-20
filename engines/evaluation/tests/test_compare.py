"""R4/D6/D10/D19/AC5/AC6: deterministic compare + explanation templates, no model call."""

from pathlib import Path

import pytest
from paudit.pack import load_pack
from paudit.result import PauditResult

from onolys_evaluation.compare import (
    compare_item,
    compare_rules,
    compare_summaries,
    explain,
    representative_instances,
)
from onolys_evaluation.report import Line
from onolys_evaluation.tone import load_report_config, tone_rules

pytestmark = pytest.mark.unit

PACK_DIR = Path(__file__).resolve().parents[3] / "protocols" / "miti-4.2.1"
FIX = PACK_DIR / "fixtures" / "evaluation"


@pytest.fixture(scope="module")
def pack():
    return load_pack(PACK_DIR)


@pytest.fixture(scope="module")
def rules(pack):
    return compare_rules(pack)


@pytest.fixture(scope="module")
def cfg():
    return load_report_config(PACK_DIR / "report.yaml")


def test_rules_read_from_pack(pack, rules):
    g, c = rules["cct"], rules["sr"]
    assert (g.kind, g.differs_at, g.within) == ("score_diff", 1, 1)
    assert (c.kind, c.flag_abs, c.flag_rel) == ("count_diff", 2, 0.25)
    assert set(rules) == set(pack.data["compare"])


@pytest.mark.parametrize("clin,ons,status,within,signed", [
    (3, 3, "agree", True, 0),
    (3, 4, "differs", True, 1),
    (4, 3, "differs", True, -1),
    (2, 4, "differs", False, 2),
])
def test_global_diffs(rules, clin, ons, status, within, signed):
    d = compare_item(rules["cct"], clin, ons)
    assert (d.status, d.within_one, d.signed, d.abs) == (status, within, signed, abs(signed))


def test_global_direction_is_onolys_minus_clinician(rules):
    assert compare_item(rules["cct"], 3, 4).direction == "onolys_higher"
    assert compare_item(rules["cct"], 4, 3).direction == "onolys_lower"
    assert compare_item(rules["cct"], 3, 3).direction == "same"


@pytest.mark.parametrize("clin,ons,status", [
    (5, 5, "agree"),
    (4, 5, "differs"),    # abs 1, ratio 0.2 < 0.25
    (0, 1, "flagged"),    # ratio 1.0
    (0, 0, "agree"),
    (10, 12, "flagged"),  # abs 2, ratio 0.167
    (3, 1, "flagged"),    # abs 2
    (3, 4, "flagged"),    # abs 1, ratio exactly 0.25
])
def test_count_diffs(rules, clin, ons, status):
    d = compare_item(rules["sr"], clin, ons)
    assert d.status == status
    assert d.signed == ons - clin and d.within_one is None


def test_count_uses_pack_thresholds(rules):
    from dataclasses import replace
    loose = replace(rules["sr"], flag_abs=5, flag_rel=0.9)
    assert compare_item(loose, 3, 5).status == "differs"


def test_not_rated_and_no_onolys_value(rules):
    d = compare_item(rules["cct"], None, 3)
    assert (d.status, d.signed, d.abs, d.direction, d.within_one) == ("not_rated", None, None, None, None)
    d = compare_item(rules["sr"], 3, None)
    assert d.status == "no_onolys_value" and d.signed is None


def _agg():
    return PauditResult.model_validate_json((FIX / "paudit_result.json").read_text())


def test_summaries_clinician_computed_via_formula(pack):
    agg = _agg().aggregate.summaries
    clin = {"cr": 3, "sr": 1, "cct": 4, "sst": 2, "partnership": 3, "empathy": 4}
    by = {s.id: s for s in compare_summaries(pack, clin, agg)}
    assert by["pct_cr"].clinician.value == pytest.approx(0.75)
    assert by["pct_cr"].clinician.label == "good"
    assert by["technical"].clinician.value == 3.0
    assert by["pct_cr"].onolys.value == agg["pct_cr"].mean
    assert by["pct_cr"].reference.good == 0.5
    assert "pass mark" in by["pct_cr"].note


def test_summary_divide_by_zero_and_missing_input_are_null(pack):
    agg = _agg().aggregate.summaries
    by = {s.id: s for s in compare_summaries(pack, {"cr": 0, "sr": 0, "cct": 4}, agg)}
    assert by["pct_cr"].clinician is None  # 0/0
    assert by["technical"].clinician is None  # sst missing


def test_summaries_no_rating(pack):
    agg = _agg().aggregate.summaries
    assert all(s.clinician is None for s in compare_summaries(pack, None, agg))


def test_partial_rating_diffs(rules):
    clin = {"cct": 4, "partnership": 5, "question": 6}
    got = {k: compare_item(rules[k], clin.get(k), 3).status for k in ("cct", "sst", "question")}
    assert got == {"cct": "differs", "sst": "not_rated", "question": "flagged"}


def test_no_rating_all_null(rules):
    assert all(compare_item(r, None, 2).signed is None for r in rules.values())


# ---- explanations ----

L = Line(turn_id="t1", start=0, end=3, quote="abc")


def _expl(pack, cfg, **kw):
    base = dict(item_id="cct", kind="global", label="Item", onolys_value=3, clinician_value=4,
                reason="Onolys reads this as a 3 because of the opening.",
                onolys_lines=[L], support_lines=[], rules=tone_rules(pack), cfg=cfg)
    base.update(kw)
    base["diff"] = base.get("diff") or compare_item(
        compare_rules(pack)[base["item_id"]], base["clinician_value"], base["onolys_value"])
    return explain(**base)


def test_explain_differs(pack, cfg):
    e, w = _expl(pack, cfg)
    assert e.headline == cfg.headline
    assert e.body[0] == "Onolys scored 3; you scored 4."
    assert e.body[1].startswith("Onolys reads this")
    assert e.onolys_lines == [L] and w == []


def test_explain_agree_headline(pack, cfg):
    e, _ = _expl(pack, cfg, clinician_value=3)
    assert e.headline != cfg.headline and "agrees" in e.headline.lower()
    assert e.onolys_lines == [L]


def test_explain_support_lines_passed_through(pack, cfg):
    s = Line(turn_id="t2", start=1, end=2, quote="x")
    e, _ = _expl(pack, cfg, support_lines=[s])
    assert e.clinician_support_lines == [s]


def test_banned_reason_withheld_with_warning(pack, cfg):
    e, w = _expl(pack, cfg, reason="This was a mistake and you are wrong.")
    assert "mistake" not in " ".join(e.body)
    assert len(e.body) == 1 and e.onolys_lines == [L]
    assert [(x.code, x.item_id) for x in w] == [("reason_withheld_tone", "cct")]


def test_not_rated_and_count_wording(pack, cfg):
    e, _ = _expl(pack, cfg, clinician_value=None)
    assert e.body[0] == "Onolys scored 3." and "you scored" not in e.body[0]
    e, _ = _expl(pack, cfg, item_id="sr", kind="count", onolys_value=2.0, clinician_value=5, reason=None)
    assert e.body == ["Onolys counted 2; you counted 5."]


def test_templates_pass_tone_lint(pack, cfg):
    from onolys_evaluation import compare
    r = tone_rules(pack)
    for s in compare.template_strings():
        assert r.lint(s) == [], s
    for s in _agg_notes(pack):
        assert r.lint(s) == [], s


def _agg_notes(pack):
    agg = _agg().aggregate.summaries
    out = []
    for clin in (None, {"cr": 3, "sr": 1}):
        out += [s.note for s in compare_summaries(pack, clin, agg)]
    return out


def test_every_quoted_line_matches_transcript(pack, cfg):
    import json
    turns = {t["id"]: t["text"] for t in json.loads((FIX / "transcript.json").read_text())["turns"]}
    res = _agg()
    rr = res.aggregate.representative_run
    lines = []
    for g in res.results[0].globals.values():
        lines += g.evidence
    for code in ("sr", "cr", "question"):
        lines += representative_instances(res, code)
    assert lines
    for ln in lines:
        assert turns[ln.turn_id][ln.start:ln.end] == ln.quote
    assert rr == res.results[0].run_index


def test_representative_instances_only_counted_code(pack):
    res = _agg()
    got = representative_instances(res, "sr")
    exp = [i for i in res.results[0].instances if i.counted and i.code == "sr"]
    assert [i.id for i in got] == [i.id for i in exp]
