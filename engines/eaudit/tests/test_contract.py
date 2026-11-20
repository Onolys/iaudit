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
    body = {
        "schema_version": "0.0.1",
        "status": 400,
        "message": "x",
        "details": [{"code": "schema_violation", "message": "x"}],
    }
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


ERROR_CODES = {
    "invalid_json",
    "unsupported_media_type",
    "schema_violation",
    "empty_transcript",
    "empty_assessment",
    "duplicate_ids",
    "invalid_parameters",
    "body_too_large",
    "too_many_turns",
    "too_many_sections",
    "rate_limited",
    "not_found",
    "method_not_allowed",
    "cors_rejected",
    "request_rejected",
    "upstream_unavailable",
    "deadline_exceeded",
    "internal_error",
}


@pytest.mark.parametrize("code", sorted(ERROR_CODES))
def test_all_error_detail_codes_are_valid(code):
    assert (
        contract.validate_error(
            {
                "schema_version": "0.0.1",
                "status": 400,
                "message": "Request rejected.",
                "details": [{"code": code, "message": "Fixed text."}],
            }
        )
        == []
    )


def test_error_code_enum_is_exact():
    schema = contract.get_contracts().error.schema
    assert (
        set(schema["properties"]["details"]["items"]["properties"]["code"]["enum"]) == ERROR_CODES
    )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("schema_version", "9.8.7"),
        ("status", 399),
        ("status", 600),
        ("status", 400.5),
        ("message", ""),
        ("details", []),
        ("details", [{"code": "other", "message": "x"}]),
        ("details", [{"code": "internal_error", "message": ""}]),
    ],
)
def test_invalid_error_fields_rejected(field, value):
    body = {
        "schema_version": "0.0.1",
        "status": 400,
        "message": "x",
        "details": [{"code": "schema_violation", "message": "x"}],
    }
    body[field] = value
    assert contract.validate_error(body)
