"""Paper context matches the supplied PRD table and stays separate from live results."""

import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from iaudit_eval.datasets import registry
from iaudit_eval.scoring import _load_references

EVAL = Path(__file__).resolve().parents[2]
PRD = EVAL.parent / "docs/agent_files/eval-tofueval-20261020/02-projection-and-metrics/PRD.md"
NOTE = "paper-reported, different model & date"
# Literal Table 3 transcription; catches any changed, missing, or transposed value.
TABLE = {
    "Baseline": [50.0, 50.0, 50.0, 50.0, 50.0, 50.0, 50.0, 50.0],
    "SummaC-ZS": [66.1, 73.9, 63.9, 80.6, 62.7, 64.1, 58.1, 72.4],
    "SummaC-CV": [67.6, 73.0, 62.6, 77.3, 61.2, 66.5, 52.4, 72.9],
    "QAFactEval": [53.9, 74.0, 58.0, 75.8, 61.4, 74.2, 55.1, 68.2],
    "AlignScore": [69.2, 76.2, 61.2, 78.6, 65.5, 72.1, 63.4, 71.8],
    "Vicuna-13B": [54.0, 54.8, 49.6, 61.9, 55.6, 59.1, 51.2, 59.2],
    "Vicuna-33B": [51.0, 51.1, 53.6, 48.4, 52.5, 53.4, 53.2, 51.0],
    "WizardLM-13B": [59.8, 53.5, 58.8, 56.6, 57.0, 54.5, 54.6, 58.0],
    "WizardLM-30B*": [54.5, 53.9, 53.5, 53.4, 53.3, 54.4, 53.0, 53.2],
    "GPT-3.5-Turbo": [61.6, 68.9, 56.0, 65.0, 59.6, 65.8, 63.2, 65.7],
    "GPT-4": [64.9, 80.2, 67.5, 90.3, 63.7, 78.9, 74.7, 83.1],
}
COLUMNS = [
    (level, dataset, topic)
    for level in ("sentence", "summary")
    for dataset in ("mediasum", "meetingbank")
    for topic in ("main", "marginal")
]


def references():
    path = EVAL / "datasets/eaudit/tofueval/references.json"
    assert path.is_file(), "Paper reference rows have not been supplied"
    return json.loads(path.read_text())


def test_every_reference_cell_matches_prd_table_and_report_schema():
    prd_rows = {}
    for line in PRD.read_text().splitlines():
        fields = [field.strip() for field in line.split("|")[1:-1]]
        if fields and fields[0] in TABLE:
            prd_rows[fields[0]] = [float(value) for value in fields[1:]]
    assert prd_rows == TABLE
    rows = references()["rows"]
    # Documentation count correction: the supplied table has 10 evaluators plus Baseline.
    assert len(rows) == 88
    schema = json.loads((EVAL / "schemas/metrics.schema.json").read_text())
    validator = Draft202012Validator({"$ref": "#/$defs/reference", "$defs": schema["$defs"]})
    actual = {}
    for row in rows:
        validator.validate(row)
        evaluator, separator, suffix = row["label"].partition(" — ")
        assert separator and suffix == f"test split; {NOTE}"
        assert row["source"] == "TofuEval paper, Table 3"
        assert row["note"] == NOTE
        assert row["metric"] == f"bacc_{row['level']}"
        assert row["slice"].keys() == {"model_group", "group_topic"}
        assert row["slice"]["model_group"] == "original_five"
        group, dataset, topic = row["slice"]["group_topic"].split("|")
        assert group == "original_five"
        key = (evaluator, row["level"], dataset, topic)
        assert key not in actual, f"Duplicate reference cell: {key}"
        actual[key] = row["value"]
    expected = {
        (evaluator, *column): percent / 100
        for evaluator, percentages in TABLE.items()
        for column, percent in zip(COLUMNS, percentages, strict=True)
    }
    assert actual == pytest.approx(expected)


def test_reference_caveats_preserve_comparability_limits():
    caveats = " ".join(references()["caveats"])
    for required in (
        "mean of 3 runs", "gpt-4-0613", "original five models only",
        "per-document", "source supplied", "no atomization", "label noise",
        "0.34", "0.42", "WizardLM-30B*", "33B",
    ):
        assert required in caveats


def test_metadata_makes_paper_rows_and_caveats_available_to_scoring(tmp_path):
    dataset = registry.load("tofueval", root=EVAL / "datasets", data_root=tmp_path)
    assert dataset.meta.references == "references.json"
    rows, caveats = _load_references(dataset, EVAL / "datasets")
    artifact = references()
    assert rows == artifact["rows"]
    assert caveats == artifact["caveats"]
    assert len(rows) == 88
