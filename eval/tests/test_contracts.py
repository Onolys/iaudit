import ast
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
    # Eval owns report schemas and the API bundle; audit schemas stay in docs/contracts/.
    own = {"metrics.schema.json", "item_rows.schema.json", "compare.schema.json"}
    found = [
        p for p in eval_dir.rglob("*.schema.json")
        if ".venv" not in p.parts and p.name not in own
        and p != eval_dir / "api" / "eval-api.schema.json"
    ]
    assert found == []


def _py_files(*rel):
    eval_dir = Path(__file__).resolve().parents[1]
    for r in rel:
        for p in (eval_dir / r).rglob("*.py"):
            if ".venv" not in p.parts and "__pycache__" not in p.parts:
                yield p


def _backend_imports(path):
    found = []
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            found += [a.name for a in node.names if a.name.split(".")[0] == "eaudit"]
        elif isinstance(node, ast.ImportFrom):
            if node.level == 0 and (node.module or "").split(".")[0] == "eaudit":
                found.append(node.module)
    return found


def test_no_backend_import_in_eval():
    files = list(_py_files("src", "datasets", "tests"))
    assert files
    bad = {str(p): _backend_imports(p) for p in files if _backend_imports(p)}
    assert bad == {}


def test_backend_import_detector_catches_violation(tmp_path):
    f = tmp_path / "x.py"
    f.write_text("import eaudit.config\nfrom eaudit import app\n")
    assert _backend_imports(f) == ["eaudit.config", "eaudit"]


def _audit_contract_copies(eval_dir):
    shared = [
        json.loads(p.read_text(encoding="utf-8"))
        for p in contracts_dir().glob("*.schema.json")
    ]
    found = []
    for path in eval_dir.rglob("*.json"):
        if ".venv" in path.parts:
            continue
        try:
            candidate = json.loads(path.read_text(encoding="utf-8"))
        except (ValueError, UnicodeError):
            continue
        if candidate in shared:
            found.append(path)
    return found


def test_no_audit_contract_content_copied_under_eval():
    assert _audit_contract_copies(Path(__file__).resolve().parents[1]) == []


def test_schema_copy_detector_catches_renamed_contract(tmp_path):
    copied = tmp_path / "renamed.json"
    shared = contracts_dir() / "audit-request.schema.json"
    copied.write_text(shared.read_text(encoding="utf-8"), encoding="utf-8")
    assert _audit_contract_copies(tmp_path) == [copied]
