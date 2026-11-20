"""R6/D6/AC6: tone lint driven by the pack's banned list; every static report string passes it."""

from pathlib import Path

import pytest
import yaml
from paudit.pack import load_pack

from onolys_evaluation.tone import (
    ReportConfigError,
    ToneRules,
    load_report_config,
    parse_report_config,
    tone_rules,
)

pytestmark = pytest.mark.unit

PACK_DIR = Path(__file__).resolve().parents[3] / "protocols" / "miti-4.2.1"


@pytest.fixture(scope="module")
def pack():
    return load_pack(PACK_DIR)


@pytest.fixture(scope="module")
def rules(pack):
    return tone_rules(pack)


def test_pack_has_banned_phrases_and_patterns(rules):
    assert len(rules.phrases) >= 6
    assert rules.patterns


def test_each_banned_phrase_is_flagged(rules):
    for ph in rules.phrases:
        hits = rules.lint(f"Here we note: {ph} in this part.")
        assert hits, ph
        assert hits[0].rule == ph


def test_phrase_flagged_case_insensitive_and_whole_word(rules):
    assert rules.lint("That was INCORRECT.")
    assert not rules.lint("A badger and incorrectness are not whole-word matches")


def test_second_person_verdicts_flagged(rules):
    for s in ["You are wrong about this.", "You missed the reflection.", "You should have asked more.",
              "You failed to explore it.", "Your mistake was timing."]:
        assert rules.lint(s), s


def test_clean_strings_pass(rules):
    for s in ["Onolys reads this as a 2 because the opening shows little partnership.",
              "Onolys disagrees, here's why", "", "The clinician asked an open question."]:
        assert rules.lint(s) == [], s


def test_violation_never_echoes_text(rules):
    secret = "zzsecretzz incorrect"
    hits = rules.lint(secret)
    assert all("zzsecretzz" not in repr(h) for h in hits)


def test_custom_rules_and_bad_regex():
    r = ToneRules.from_spec({"phrases": ["nope"], "patterns": [r"\bdo it again\b"]})
    assert r.lint("well, NOPE") and r.lint("do it again") and not r.lint("fine")
    with pytest.raises(ReportConfigError):
        ToneRules.from_spec({"phrases": [], "patterns": ["("]})
    with pytest.raises(ReportConfigError):
        ToneRules.from_spec({"phrases": "nope"})
    with pytest.raises(ReportConfigError):
        ToneRules.from_spec(None)


def test_every_static_report_string_passes_the_lint(pack, rules):
    cfg = load_report_config(pack.root / "report.yaml")
    strings = cfg.static_strings()
    assert cfg.headline in strings and cfg.method.statement in strings
    assert len(strings) >= 8
    bad = [(s, rules.lint(s)) for s in strings if rules.lint(s)]
    assert bad == []


def test_layout_loads_from_pack_yaml(pack):
    cfg = load_report_config(pack.root / "report.yaml")
    assert cfg.headline == "Onolys disagrees, here's why"
    assert [s.id for s in cfg.sections] == [s["id"] for s in pack.report["sections"]]
    assert cfg.max_instances_shown >= 1
    assert cfg.method.limits and cfg.method.citation
    assert all(isinstance(s.enabled, bool) for s in cfg.sections)
    assert cfg.layout()[0] == {"section": "globals", "title": "Global ratings",
                               "items": ["cct", "sst", "partnership", "empathy"]}


def test_disabled_section_dropped_from_layout():
    cfg = parse_report_config(_good(sections=[
        {"id": "a", "label": "A", "items": ["x"]},
        {"id": "b", "label": "B", "enabled": False}]))
    assert [e["section"] for e in cfg.layout()] == ["a"]


def _good(**over):
    base = {
        "headline": "h", "max_instances_shown": 3,
        "method": {"statement": "s", "limits": ["l"], "citation": "c"},
        "sections": [{"id": "a", "label": "A", "items": ["x"]}],
    }
    return {**base, **over}


@pytest.mark.parametrize("mutate,needle", [
    (lambda d: d.pop("headline"), "headline"),
    (lambda d: d.update(max_instances_shown=0), "max_instances_shown"),
    (lambda d: d.update(max_instances_shown="3"), "max_instances_shown"),
    (lambda d: d.update(method={"statement": "s"}), "method"),
    (lambda d: d.update(method={"statement": "s", "limits": "no", "citation": "c"}), "limits"),
    (lambda d: d.update(sections=[]), "sections"),
    (lambda d: d.update(sections=[{"id": "a"}]), "label"),
    (lambda d: d.update(sections=[{"id": "a", "label": "A"}, {"id": "a", "label": "B"}]), "duplicate"),
    (lambda d: d.update(sections="x"), "sections"),
])
def test_malformed_config_gives_clear_error(mutate, needle):
    d = _good()
    mutate(d)
    with pytest.raises(ReportConfigError, match=needle):
        parse_report_config(d)


def test_non_mapping_and_bad_yaml_file(tmp_path):
    with pytest.raises(ReportConfigError, match="mapping"):
        parse_report_config(["a"])
    p = tmp_path / "report.yaml"
    p.write_text("sections: [unclosed", encoding="utf-8")
    with pytest.raises(ReportConfigError, match="report.yaml"):
        load_report_config(p)
    with pytest.raises(ReportConfigError, match="not found"):
        load_report_config(tmp_path / "nope.yaml")
    p.write_text(yaml.safe_dump(_good()), encoding="utf-8")
    assert load_report_config(p).headline == "h"
