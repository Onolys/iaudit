"""Task 8: `build_report` assembly (R7, D12, D13, AC8). Inputs come from the fixture generator."""

import json
from pathlib import Path

import pytest
import yaml
from _make_fixtures import FULL_RATING, PACK, inputs
from conftest import SCHEMA_PATH
from jsonschema import Draft202012Validator
from onolys_core.run_info import RunInfo
from paudit.pack import load_pack

from onolys_evaluation.api import build_report
from onolys_evaluation.compare import template_strings
from onolys_evaluation.hashes import evaluation_prompt_hashes
from onolys_evaluation.tone import load_report_config, tone_rules

pytestmark = pytest.mark.unit

VARIANTS = ("full", "partial", "no_rating")


def doc(variant):
    return json.loads(build_report(**inputs(variant)).model_dump_json())


@pytest.fixture(scope="module")
def validator():
    return Draft202012Validator(json.loads(SCHEMA_PATH.read_text(encoding="utf-8")))


@pytest.mark.parametrize("variant", VARIANTS)
def test_validates_schema(variant, validator):
    errors = list(validator.iter_errors(doc(variant)))
    assert not errors, errors[:3]


@pytest.mark.parametrize("variant", VARIANTS)
def test_layout_follows_report_yaml(variant):
    want = yaml.safe_load((PACK / "report.yaml").read_text(encoding="utf-8"))["sections"]
    got = doc(variant)["layout"]
    assert [e["section"] for e in got] == [s["id"] for s in want]
    assert [e["title"] for e in got] == [s["label"] for s in want]


def test_disabled_section_left_out_of_layout():
    kw = inputs("full")
    cfg = load_report_config(PACK / "report.yaml")
    from dataclasses import replace

    secs = [replace(s, enabled=False) if s.id == "tips" else s for s in cfg.sections]
    r = build_report(**kw, cfg=replace(cfg, sections=secs))
    assert "tips" not in [e.section for e in r.layout]


def test_aggregates_full_hand_computed():
    # clinician cct3 sst4 partnership5 empathy3 vs onolys 4,4,5,4 -> abs 1,0,0,1
    a = doc("full")["aggregates"]
    assert a == {"globals_compared": 4, "avg_abs_global_difference": 0.5,
                 "within_one_share": 1.0,
                 "counts_flagged": 4}  # gi 2v1, sr 4v2, cr 3v4, emphasize_autonomy 1v2


def test_aggregates_partial_hand_computed():
    # rated: cct 4 (onolys 4), partnership 5 (5), question 6 (6), cr 3 (4)
    a = doc("partial")["aggregates"]
    assert a == {"globals_compared": 2, "avg_abs_global_difference": 0.0,
                 "within_one_share": 1.0, "counts_flagged": 1}


def test_within_one_share_below_one():
    kw = inputs("full")
    kw["rating"] = {**FULL_RATING, "globals": {
        **FULL_RATING["globals"], "cct": {"score": 1, "reason": "x"}}}  # abs 3
    a = build_report(**kw).aggregates
    assert a.globals_compared == 4
    assert a.within_one_share == 0.75
    assert a.avg_abs_global_difference == (3 + 0 + 0 + 1) / 4


def test_no_rating_nulls_and_skipped():
    d = doc("no_rating")
    assert d["aggregates"] == {"globals_compared": 0, "avg_abs_global_difference": None,
                               "within_one_share": None, "counts_flagged": None}
    assert d["reasons_audit"] == {"status": "skipped", "items": []}
    assert d["header"]["has_clinician_rating"] is False
    assert d["header"]["rating_coverage"] == {"rated": 0, "total": 14}
    assert all(r["clinician"]["value"] is None for r in d["scorecard"])
    assert all(r["diff"]["status"] == "not_rated" for r in d["scorecard"])
    assert len(d["tips"]) >= 3 and d["method"]["statement"]
    assert d["run_info"]["eaudit"] is None


def test_rating_coverage():
    assert doc("full")["header"]["rating_coverage"] == {"rated": 14, "total": 14}
    assert doc("partial")["header"]["rating_coverage"] == {"rated": 4, "total": 14}


@pytest.mark.parametrize("variant", VARIANTS)
def test_header_fields(variant):
    kw = inputs(variant)
    h = doc(variant)["header"]
    assert h["stt"] == json.loads(kw["transcript"].stt_run.model_dump_json())
    assert h["stt"] is not None
    assert h["preset"] == "fixture" and h["code_version"] == "fixture"
    assert h["protocol"]["pack_hash"] == kw["pack"].pack_hash
    assert h["n_runs"] == kw["paudit_result"].n_runs
    assert h["subject_speaker"] == kw["speaker_map"]["subject"]


def test_text_only_transcript_has_null_stt():
    kw = inputs("full")
    kw["transcript"] = kw["transcript"].model_copy(update={"stt_run": None})
    r = build_report(**kw)
    assert r.header.stt is None and r.run_info.evaluation.stt is None


@pytest.mark.parametrize("variant", VARIANTS)
def test_method_from_pack_and_not_official(variant):
    cfg = load_report_config(PACK / "report.yaml")
    m = doc(variant)["method"]
    assert m["statement"] == cfg.method.statement
    assert m["not_official_miti_coding"] is True
    assert m["citation"] == cfg.method.citation
    assert m["limits"][:-1] == cfg.method.limits
    assert "not an official coding" in m["limits"][-1]
    assert not tone_rules(load_pack(PACK)).lint(m["limits"][-1])


def test_reasons_status_and_warnings():
    assert doc("full")["reasons_audit"]["status"] == "ran"
    p = doc("partial")
    assert p["reasons_audit"]["status"] == "partial"
    assert {"code": "reasons_audit_partial", "item_id": None} in p["warnings"]
    kw = inputs("full")
    kw["reasons_items"], kw["reasons_failed"] = None, True
    r = build_report(**kw)
    assert r.reasons_audit.status == "failed" and r.reasons_audit.items == []
    assert "reasons_audit_failed" in [w.code for w in r.warnings]


def test_extra_warnings_passed_through_and_deduped():
    from onolys_evaluation.report import Warning

    kw = inputs("full")
    kw["warnings"] = [Warning(code="fewer_tips"), Warning(code="fewer_tips")]
    assert [w.code for w in build_report(**kw).warnings].count("fewer_tips") == 1


def test_never_truncates_instances():
    kw = inputs("full")
    r = build_report(**kw)
    cfg = load_report_config(PACK / "report.yaml")
    for b in r.behaviours:
        assert b.instances_total == len(b.instances)
    # all counted instances of the representative run are present, regardless of the UI cap
    res = kw["paudit_result"]
    run = next(x for x in res.results if x.run_index == res.aggregate.representative_run)
    assert sum(b.instances_total for b in r.behaviours) == sum(
        1 for i in run.instances if i.counted)
    assert cfg.max_instances_shown >= 1


def test_scorecard_and_sections_cover_pack_items():
    d = doc("full")
    assert [r["item_id"] for r in d["scorecard"]][:4] == ["cct", "sst", "partnership", "empathy"]
    assert len(d["scorecard"]) == 14 and len(d["globals"]) == 4 and len(d["behaviours"]) == 10
    cct = d["globals"][0]
    assert cct["clinician"]["reason"] == FULL_RATING["globals"]["cct"]["reason"]
    assert cct["diff"]["signed"] == 1.0 and cct["diff"]["direction"] == "onolys_higher"
    assert cct["explanation"]["clinician_support_lines"]  # from supported reasons-audit evidence
    assert len(d["summaries"]) == 6


def test_no_suggested_revision_anywhere():
    assert "suggested_revision" not in json.dumps(doc("full"))


@pytest.mark.parametrize("variant", VARIANTS)
def test_run_info_has_no_text_and_core_shape(variant):
    d = doc(variant)
    ri = d["run_info"]
    RunInfo.model_validate(ri["evaluation"])
    blob = json.dumps(ri)
    for text in (FULL_RATING["notes"], FULL_RATING["globals"]["cct"]["reason"],
                 inputs(variant)["transcript"].turns[0].text):
        assert text not in blob
    assert ri["evaluation"]["pack"]["hash"] == d["header"]["protocol"]["pack_hash"]


def test_prompt_hashes_cover_pack_tips_prompts_and_engine_templates():
    pack = load_pack(PACK)
    h = evaluation_prompt_hashes(pack)
    assert "tips_system.md" in h
    assert {"engine:tips_output_format", "engine:compare_templates"} <= set(h)
    assert all(len(v) == 16 for v in h.values())
    assert doc("full")["run_info"]["evaluation"]["prompt_hashes"] == h
    # a pack tips-prompt change changes the hash
    import shutil
    import tempfile

    with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as tmp:
        root = Path(tmp) / "pack"
        shutil.copytree(PACK, root, ignore=shutil.ignore_patterns("fixtures"))
        (root / "prompts" / "tips_system.md").write_text("changed", encoding="utf-8")
        assert evaluation_prompt_hashes(load_pack(root))["tips_system.md"] != h["tips_system.md"]


def test_compare_template_hash_tracks_templates(monkeypatch):
    import onolys_evaluation.compare as c
    import onolys_evaluation.hashes as hashes

    pack = load_pack(PACK)
    before = hashes.evaluation_prompt_hashes(pack)["engine:compare_templates"]
    monkeypatch.setattr(c, "SCORED", "changed {o} {c}")
    assert template_strings() != []
    assert hashes.evaluation_prompt_hashes(pack)["engine:compare_templates"] != before
