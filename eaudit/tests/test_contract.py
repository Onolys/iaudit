import copy
import subprocess
import sys

import pytest

from eaudit import contract


def test_example_request_valid(example_request):
    assert contract.validate_request(example_request) == []


def test_example_response_valid(example_response):
    assert contract.validate_response(example_response) == []


def test_error_example_valid():
    body = {"schema_version": "1.2.0", "error": {"code": "other", "message": "x"}}
    assert contract.validate_error(body) == []


def test_invalid_request_reports_path_not_value(example_request):
    bad = copy.deepcopy(example_request)
    bad["transcript"][0]["text"] = 5
    bad["transcript"][0]["speaker"] = "SENTINEL-VALUE"
    bad["extra"] = "SENTINEL-VALUE"
    issues = contract.validate_request(bad)
    assert issues
    assert any(i.path.startswith("transcript/0") for i in issues)
    # messages never contain instance values
    assert all("SENTINEL" not in i.message for i in issues)


def test_invalid_response_detected(example_response):
    bad = copy.deepcopy(example_response)
    bad["status"] = "weird"
    assert contract.validate_response(bad)


def test_missing_contracts_dir_fails_startup(tmp_path):
    with pytest.raises(contract.ContractError, match="contracts"):
        contract.load_contracts(tmp_path / "nope")


def test_invalid_schema_fails(tmp_path):
    for n in ("audit-request", "audit-response", "error-response"):
        (tmp_path / f"{n}.schema.json").write_text('{"type": 12}')
    with pytest.raises(contract.ContractError):
        contract.load_contracts(tmp_path)


def test_env_override_fails_import_clearly(tmp_path):
    r = subprocess.run(
        [sys.executable, "-c", "from eaudit import contract; contract.get_contracts()"],
        env={"IAUDIT_CONTRACTS_DIR": str(tmp_path / "missing"), "PATH": ""},
        capture_output=True,
        text=True,
    )
    assert r.returncode != 0
    assert "contracts" in r.stderr.lower()
