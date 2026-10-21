import json
from pathlib import Path

import pytest

from iaudit_eval import contracts
from iaudit_eval.paths import contracts_dir, repo_root

EXAMPLES = repo_root() / "docs" / "contracts" / "examples"
SENTINEL = "SENTINEL_SECRET_42"


def _load(name):
    return json.loads((EXAMPLES / name).read_text(encoding="utf-8"))


def test_examples_validate():
    assert contracts.validate_request(_load("request.json")) == []
    assert contracts.validate_response(_load("response.json")) == []
    assert contracts.validate_error(_load("error.json")) == []


def test_bad_instances_report_issues():
    assert contracts.validate_request({})
    assert contracts.validate_response([])


def test_sentinel_never_in_issues():
    req = _load("request.json")
    req["schema_version"] = SENTINEL
    req[SENTINEL] = SENTINEL
    req["transcript"][0]["role"] = SENTINEL
    req["transcript"][1]["text"] = 5
    req["transcript"].append({SENTINEL: SENTINEL})
    resp = _load("response.json")
    resp["status"] = SENTINEL
    resp["claims"] = {SENTINEL: SENTINEL}
    for issues in (
        contracts.validate_request(req, limit=None),
        contracts.validate_response(resp, limit=None),
        contracts.validate_error({"schema_version": SENTINEL, SENTINEL: 1}, limit=None),
    ):
        assert issues
        assert SENTINEL not in " ".join(str(i) for i in issues)
        assert all(SENTINEL not in i.path and SENTINEL not in i.message for i in issues)


def test_limit():
    assert len(contracts.validate_request({}, limit=1)) == 1


def test_schema_version_read_from_schema():
    v = contracts.schema_version()
    schema = json.loads((contracts_dir() / "audit-request.schema.json").read_text())
    assert v == schema["properties"]["schema_version"]["const"]
    assert _load("request.json")["schema_version"] == v


def test_missing_dir(tmp_path):
    with pytest.raises(contracts.ContractError):
        contracts.load_contracts(tmp_path / "nope")


def test_invalid_schema_file(tmp_path):
    for n in ("audit-request", "audit-response", "error-response"):
        (tmp_path / f"{n}.schema.json").write_text("{not json")
    with pytest.raises(contracts.ContractError):
        contracts.load_contracts(tmp_path)


def test_no_schema_copy_under_eval():
    eval_dir = Path(__file__).resolve().parents[1]
    found = [p for p in eval_dir.rglob("*.schema.json") if ".venv" not in p.parts]
    assert found == []
