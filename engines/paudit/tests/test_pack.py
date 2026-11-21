import copy
import json

import pytest
from conftest import PACK_YAML, PROMPTS, write_pack
from onolys_core import PackError

from paudit.pack import PACK_FORMAT, load_pack, pack_schema

pytestmark = pytest.mark.unit


def load_with(tmp_path, **kw):
    return load_pack(write_pack(tmp_path / "p", **kw))


# --- resolution ---------------------------------------------------------------------------

def test_loads_by_ref_under_protocols_dir(protocols):
    pack = load_pack("demo@1.0.0", protocols_dir=protocols)
    assert (pack.id, pack.version, pack.pack_format) == ("demo", "1.0.0", "0.0.1")
    assert PACK_FORMAT == "0.0.1"
    assert [i["id"] for i in pack.items] == ["g1", "g2", "a", "b", "c"]
    assert pack.ref().path == str(pack.root)


def test_loads_by_path(tmp_path):
    assert load_with(tmp_path).id == "demo"


def test_protocols_dir_from_env(protocols, monkeypatch):
    monkeypatch.setenv("PAUDIT_PROTOCOLS_DIR", str(protocols))
    assert load_pack("demo@1.0.0").version == "1.0.0"


def test_missing_pack_is_pack_error(tmp_path):
    with pytest.raises(PackError):
        load_pack("nope@9", protocols_dir=tmp_path)


def test_id_version_must_match_directory_ref(protocols):
    (protocols / "demo-2.0.0").mkdir()
    write_pack(protocols / "demo-2.0.0")  # pack.yaml says 1.0.0
    with pytest.raises(PackError, match="version"):
        load_pack("demo@2.0.0", protocols_dir=protocols)


# --- schema -------------------------------------------------------------------------------

def test_schema_is_valid_json_and_pins_format():
    assert pack_schema()["properties"]["pack_format"]["const"] == "0.0.1"


def test_evaluation_key_accepts_any_object(tmp_path, pack_data):
    pack_data["evaluation"] = {"deep": {"nested": [1, 2, {"x": None}]}}
    assert load_with(tmp_path, pack=pack_data).data["evaluation"]["deep"]["nested"][2] == {"x": None}


def test_evaluation_key_is_optional(tmp_path, pack_data):
    del pack_data["evaluation"]
    load_with(tmp_path, pack=pack_data)


def mutate(fn):
    d = copy.deepcopy(PACK_YAML)
    fn(d)
    return d


BAD = {
    "wrong_format": lambda d: d.update(pack_format="0.0.2"),
    "missing_id": lambda d: d.pop("id"),
    "missing_items": lambda d: d.pop("items"),
    "unknown_top_key": lambda d: d.update(surprise=1),
    "bad_item_kind": lambda d: d["items"][0].update(kind="nope"),
    "global_without_scale": lambda d: d["items"][0].pop("scale"),
    "scale_default_out_of_range": lambda d: d["items"][0]["scale"].update(default=9),
    "cap_without_source": lambda d: d["items"][0]["caps"][0].pop("source"),
    "cap_bad_when": lambda d: d["items"][0]["caps"][0].update(when="always"),
    "bad_rule_kind": lambda d: d["rules"][0].update(kind="mystery"),
    "bad_severity": lambda d: d["input_checks"][0].update(severity="fatal"),
    "bad_check_kind": lambda d: d["input_checks"][0].update(kind="mystery"),
    "bad_volley": lambda d: d["volley"].update(breaks_on="never"),
    "summary_no_expr": lambda d: d["summaries"][0].pop("expr"),
    "bad_param_type": lambda d: d["params"].update(code_max_tokens="lots"),
    "evaluation_not_object": lambda d: d.update(evaluation=[1]),
    "bad_item_id": lambda d: d["items"][2].update(id="Has Space"),
}


@pytest.mark.parametrize("name", BAD)
def test_schema_rejects(tmp_path, name):
    with pytest.raises(PackError):
        load_with(tmp_path, pack=mutate(BAD[name]))


def test_malformed_yaml_is_pack_error(tmp_path):
    root = write_pack(tmp_path / "p")
    (root / "pack.yaml").write_text("a: [unclosed")
    with pytest.raises(PackError):
        load_pack(root)


# --- parity -------------------------------------------------------------------------------

def test_parity_rating_missing_item(tmp_path, rating):
    del rating["properties"]["counts"]["properties"]["c"]
    with pytest.raises(PackError, match="rating"):
        load_with(tmp_path, rating=rating)


def test_parity_rating_extra_item(tmp_path, rating):
    rating["properties"]["globals"]["properties"]["zzz"] = {}
    with pytest.raises(PackError, match="rating"):
        load_with(tmp_path, rating=rating)


def test_parity_rating_item_in_wrong_section(tmp_path, rating):
    rating["properties"]["counts"]["properties"]["g1"] = {}
    del rating["properties"]["globals"]["properties"]["g1"]
    with pytest.raises(PackError, match="rating"):
        load_with(tmp_path, rating=rating)


def test_parity_rating_schema_must_be_json(tmp_path):
    root = write_pack(tmp_path / "p")
    (root / "rating.schema.json").write_text("{nope")
    with pytest.raises(PackError):
        load_pack(root)


def test_parity_report_unknown_id(tmp_path):
    with pytest.raises(PackError, match="report"):
        load_with(tmp_path, report={"sections": [{"id": "x", "label": "X", "items": ["ghost"]}]})


def test_parity_report_missing_file(tmp_path):
    root = write_pack(tmp_path / "p")
    (root / "report.yaml").unlink()
    with pytest.raises(PackError, match="report"):
        load_pack(root)


def test_parity_compare_unknown_id(tmp_path, pack_data):
    pack_data["compare"]["ghost"] = {"kind": "within"}
    with pytest.raises(PackError, match="compare"):
        load_with(tmp_path, pack=pack_data)


@pytest.mark.parametrize("missing", sorted(PROMPTS))
def test_parity_prompt_file_missing(tmp_path, missing):
    prompts = {k: v for k, v in PROMPTS.items() if k != missing}
    with pytest.raises(PackError, match=missing):
        load_with(tmp_path, prompts=prompts)


def test_parity_precedence_not_subset_of_group(tmp_path, pack_data):
    pack_data["rules"][2]["precedence"] = ["c", "a"]
    with pytest.raises(PackError, match="precedence"):
        load_with(tmp_path, pack=pack_data)


def test_parity_rule_unknown_code(tmp_path, pack_data):
    pack_data["rules"][2]["codes"] = ["b", "ghost"]
    pack_data["rules"][2]["precedence"] = ["b"]
    with pytest.raises(PackError, match="ghost"):
        load_with(tmp_path, pack=pack_data)


def test_parity_formula_unknown_id(tmp_path, pack_data):
    pack_data["summaries"][0]["expr"] = "a/ghost"
    with pytest.raises(PackError, match="ghost"):
        load_with(tmp_path, pack=pack_data)


@pytest.mark.parametrize("expr", ["__import__('os')", "a.real", "max(a, b)", "a if b else c", "a +", "a**b"])
def test_parity_formula_must_be_plain_arithmetic(tmp_path, pack_data, expr):
    pack_data["summaries"][0]["expr"] = expr
    with pytest.raises(PackError, match="formula"):
        load_with(tmp_path, pack=pack_data)


def test_parity_duplicate_item_ids(tmp_path, pack_data):
    pack_data["items"].append(dict(pack_data["items"][2]))
    with pytest.raises(PackError, match="duplicate"):
        load_with(tmp_path, pack=pack_data)


def test_parity_summary_id_clashes_with_item(tmp_path, pack_data):
    pack_data["summaries"][0]["id"] = "a"
    with pytest.raises(PackError, match="duplicate"):
        load_with(tmp_path, pack=pack_data)


# --- pack_hash ----------------------------------------------------------------------------

def test_hash_stable_across_loads_and_locations(tmp_path):
    a = load_pack(write_pack(tmp_path / "one"))
    b = load_pack(write_pack(tmp_path / "two"))
    assert a.pack_hash == b.pack_hash == load_pack(tmp_path / "one").pack_hash
    assert len(a.pack_hash) == 16


@pytest.mark.parametrize("rel", ["pack.yaml", "rules.py", "rating.schema.json", "report.yaml",
                                 "prompts/code_system.md", "prompts/globals_fewshot.json"])
def test_hash_changes_when_covered_file_edited(tmp_path, rel):
    root = write_pack(tmp_path / "p")
    before = load_pack(root).pack_hash
    f = root / rel
    f.write_text(f.read_text() + "\n# edit\n" if rel != "rating.schema.json" else json.dumps(
        {**json.loads(f.read_text()), "title": "t"}))
    if rel == "pack.yaml":
        f.write_text(f.read_text().replace("Global one", "Global uno"))
    assert load_pack(root).pack_hash != before


def test_hash_ignores_fixtures(tmp_path):
    root = write_pack(tmp_path / "p")
    before = load_pack(root).pack_hash
    (root / "fixtures").mkdir()
    (root / "fixtures" / "expected.yaml").write_text("a: 1")
    assert load_pack(root).pack_hash == before
    (root / "fixtures" / "expected.yaml").write_text("a: 2")
    assert load_pack(root).pack_hash == before


def test_hash_without_rules_py(tmp_path):
    root = write_pack(tmp_path / "p", rules_py=None)
    pack = load_pack(root)
    assert pack.rules_path is None
    assert pack.pack_hash != load_pack(write_pack(tmp_path / "q")).pack_hash


def test_pack_facts_for_run_info(tmp_path):
    pack = load_with(tmp_path)
    facts = pack.facts()
    assert (facts.id, facts.version, facts.hash) == ("demo", "1.0.0", pack.pack_hash)
