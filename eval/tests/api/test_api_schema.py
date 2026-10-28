"""The published API contract stays usable offline as a single JSON Schema."""

import copy
import importlib.util
import json
import subprocess
import sys
from dataclasses import asdict

import pytest
from jsonschema import Draft202012Validator
from pydantic import TypeAdapter, ValidationError

from iaudit_eval import paths
from iaudit_eval.estimate import Estimate as EngineEstimate


def api_modules():
    # A missing implementation must be an assertion failure during the initial red run.
    assert importlib.util.find_spec("iaudit_eval.server.models"), "API models are not implemented"
    from iaudit_eval.server import export_schema, models

    return models, export_schema


def validator(name):
    _, exporter = api_modules()
    schema = exporter.build_schema()
    return Draft202012Validator({"$ref": f"#/$defs/{name}", **schema})


def test_committed_schema_is_current():
    _, exporter = api_modules()
    assert exporter.schema_path().read_text() == exporter.render_schema()


def test_export_command_writes_schema(tmp_path):
    _, exporter = api_modules()
    output = tmp_path / "eval-api.schema.json"
    subprocess.run(
        [sys.executable, "-m", "iaudit_eval.server.export_schema", "--output", str(output)],
        check=True,
    )
    assert json.loads(output.read_text()) == exporter.build_schema()


@pytest.mark.parametrize("name,filename", [("MetricsReport", "metrics.schema.json"), ("Comparison", "compare.schema.json")])
def test_bundled_reports_equal_b3_source(name, filename):
    _, exporter = api_modules()
    assert exporter.build_schema()["$defs"][name] == json.loads((paths.schemas_dir() / filename).read_text())


def test_nested_report_references_resolve_without_fetching():
    # Exercise nested $id scopes and their #/$defs references, including names shared
    # by both bundled reports. A shallow copy/flattening bug fails here.
    from test_metrics_schema import good_report

    metrics = good_report()
    validator("MetricsReport").validate(metrics)
    metrics["entries"][0]["n"] = -1
    assert not validator("MetricsReport").is_valid(metrics)
    comparison = {
        "schema_version": "0.0.1", "run_a": "a", "run_b": "b", "dataset": "synthetic",
        "warnings": [], "n_shared": 1, "n_a_only": 0, "n_b_only": 0, "n_clusters_shared": 1,
        "deltas": [{"metric": "accuracy", "level": "item", "policy": "primary", "slice": {},
                    "a": {"value": 1, "n": 1, "ci": None}, "b": {"value": 0, "n": 1, "ci": None},
                    "delta": -1, "delta_ci": None, "ci_status": "few_clusters", "n_clusters": 1}],
        "disagreements": [{"item_id": "i", "cluster": "c", "pairs": [
            {"level": "item", "unit": "", "gold": "yes", "a": "yes", "b": None}]}],
    }
    validator("Comparison").validate(comparison)
    comparison["deltas"][0]["b"]["n"] = -1
    assert not validator("Comparison").is_valid(comparison)


def test_route_map_covers_all_prd_endpoints_and_errors():
    _, exporter = api_modules()
    schema = exporter.build_schema()
    assert schema["x-routes"] == {
        "GET /health": "Health", "GET /datasets": "DatasetSummary[]",
        "GET /datasets/{name}": "DatasetMeta", "POST /datasets/{name}/download": "DownloadStatus",
        "GET /datasets/{name}/download": "DownloadStatus", "POST /runs/estimate": "Estimate",
        "POST /runs": "RunCreated", "GET /runs": "RunSummary[]", "GET /runs/{id}": "RunDetail",
        "POST /runs/{id}/abort": "RunSummary", "POST /runs/{id}/resume": "RunSummary",
        "GET /runs/{id}/metrics": "MetricsReport", "GET /runs/{id}/items": "ItemPage",
        "GET /runs/{id}/items/{item_id}": "ItemDetail", "POST /runs/{id}/rescore": "RunSummary",
        "GET /compare": "Comparison",
    }
    assert schema["x-errors"] == {str(status): "ErrorResponse" for status in (403, 404, 409, 422, 500, 502)}
    for definition in [*schema["x-routes"].values(), *schema["x-errors"].values()]:
        assert definition.removesuffix("[]") in schema["$defs"]
    Draft202012Validator.check_schema(schema)


def test_estimate_preserves_b2_payload_with_nullable_usage():
    models, _ = api_modules()
    estimate = asdict(EngineEstimate("none", 5, None, None, None, True, "No prior runs."))
    assert models.Estimate.model_validate(estimate).model_dump() == estimate
    validator("Estimate").validate(estimate)
    estimate["rough"] = False
    assert not validator("Estimate").is_valid(estimate)


@pytest.mark.parametrize("request_name", ["EstimateRequest", "RunRequest"])
def test_requests_reject_invalid_selection_and_unknown_fields(request_name):
    models, _ = api_modules()
    model = getattr(models, request_name)
    assert model(dataset="synthetic", split="all").n is None
    for invalid in ({"n": 0}, {"dataset": "../secret"}, {"split": ""}, {"typo": True}):
        with pytest.raises(ValidationError):
            model.model_validate({"dataset": "synthetic", "split": "all", **invalid})
    if request_name == "RunRequest":
        with pytest.raises(ValidationError):
            model(dataset="synthetic", split="all", max_cost_usd=-1)
        assert model(dataset="synthetic", split="all", tags={"contamination": "possible"}).tags == {"contamination": "possible"}


def test_item_rows_derive_from_b3_and_allow_unscored_nulls():
    models, _ = api_modules()
    from iaudit_eval.metrics.report import ItemRow as B3ItemRow

    assert issubclass(models.ItemRow, dict)
    assert set(models.ItemRow.__annotations__) == set(B3ItemRow.__annotations__)
    row = {"item_id": "a", "status": "ok", "gold": None, "pred": None, "match": None}
    assert TypeAdapter(models.ItemRow).validate_python(row) == row
    validator("ItemPage").validate({"total": 1, "items": [row]})
    scored_row = {**row, "gold": "True", "pred": "False", "match": False,
                  "detail": {"opaque": [1, {"custom": True}]}}
    assert TypeAdapter(models.ItemRow).validate_python(scored_row) == scored_row
    for bad in ({"status": "finished"}, {"gold": 3}, {"match": "false"}, {"unexpected": True}):
        assert not validator("ItemPage").is_valid({"total": 1, "items": [{**row, **bad}]})


@pytest.mark.parametrize("name,field,values", [
    ("RunSummary", "state", ["running", "finished", "aborted", "aborted_cost", "interrupted", "failed"]),
    ("RunSummary", "score_state", ["pending", "running", "done", "failed"]),
    ("DownloadStatus", "status", ["not_downloaded", "downloading", "ready", "failed"]),
    ("Error", "code", ["invalid_request", "not_found", "run_active", "bad_state", "data_missing", "backend_unreachable", "schema_mismatch", "forbidden", "internal_error"]),
])
def test_schema_closes_prd_enums(name, field, values):
    _, exporter = api_modules()
    definition = exporter.build_schema()["$defs"][name]["properties"][field]
    assert set(definition["enum"]) == set(values)


def test_item_detail_preserves_opaque_gold_and_failure():
    models, _ = api_modules()
    detail = {"item_id": "a", "status": "failed", "request": {"schema_version": "0.0.1"},
              "response": None, "failure": {"reason": "timeout", "custom": {"retry": False}},
              "run_info": None, "gold": {"sentences": [{"label": "supported"}]},
              "gold_kind": "tofueval_summary_sentences"}
    assert models.ItemDetail.model_validate(copy.deepcopy(detail)).model_dump() == detail
    validator("ItemDetail").validate(detail)
