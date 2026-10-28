"""Contract 0.0.1 schema rules, loaded directly (independent of backend version constant)."""

import copy
import json
from pathlib import Path

import jsonschema
import pytest

CONTRACTS = Path(__file__).resolve().parents[2] / "docs" / "contracts"
EXAMPLES = CONTRACTS / "examples"


def _schema(name):
    return json.loads((CONTRACTS / f"{name}.schema.json").read_text())


def _validator(name):
    schema = _schema(name)
    jsonschema.Draft202012Validator.check_schema(schema)
    return jsonschema.Draft202012Validator(schema)


def _kind(path: Path) -> str:
    if path.name == "error.json":
        return "error-response"
    if path.name.endswith("request.json"):
        return "audit-request"
    return "audit-response"


@pytest.mark.parametrize("path", sorted(EXAMPLES.glob("*.json")), ids=lambda p: p.name)
def test_every_example_validates(path):
    _validator(_kind(path)).validate(json.loads(path.read_text()))


@pytest.mark.parametrize("name", ["audit-request", "audit-response", "error-response"])
def test_schema_version_is_1_1_0(name):
    assert _schema(name)["properties"]["schema_version"]["const"] == "0.0.1"


def test_response_example_carries_run_info_and_partial_omits_it():
    assert "run_info" in json.loads((EXAMPLES / "response.json").read_text())
    assert "run_info" not in json.loads((EXAMPLES / "partial.response.json").read_text())


@pytest.fixture
def base():
    return json.loads((EXAMPLES / "response.json").read_text())


def _errors(body):
    return list(_validator("audit-response").iter_errors(body))


def test_run_info_without_token_or_cost_accepted(base):
    info = base["run_info"]
    for k in ("input_tokens", "output_tokens", "cache_read_tokens", "cache_write_tokens", "cost_usd"):
        info.pop(k, None)
    assert _errors(base) == []


def test_run_info_with_tokens_and_cost_accepted(base):
    base["run_info"].update(
        input_tokens=1, output_tokens=2, cache_read_tokens=0, cache_write_tokens=3, cost_usd=0.0
    )
    assert _errors(base) == []


def test_run_info_omitted_accepted(base):
    del base["run_info"]
    assert _errors(base) == []


@pytest.mark.parametrize(
    "mutate",
    [
        lambda i: i.update(transcript="x"),
        lambda i: i["models"].update(extra="x"),
        lambda i: i["prompt_hashes"].update(extra="0" * 16),
        lambda i: i.update(cost_usd=-0.01),
        lambda i: i.update(input_tokens=-1),
        lambda i: i.update(output_tokens=1.5),
        lambda i: i["prompt_hashes"].update(atomize="abc"),
        lambda i: i["prompt_hashes"].update(link="G" * 16),
        lambda i: i["prompt_hashes"].update(check="A" * 16),
        lambda i: i["prompt_hashes"].update(prep="0" * 17),
        lambda i: i.pop("models"),
        lambda i: i.pop("prompt_hashes"),
        lambda i: i["models"].pop("strong"),
        lambda i: i["prompt_hashes"].pop("prep"),
    ],
)
def test_run_info_rejects(base, mutate):
    mutate(base["run_info"])
    assert _errors(copy.deepcopy(base))
