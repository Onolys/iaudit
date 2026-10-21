import json

from iaudit_backend.contract import default_contracts_dir
from iaudit_backend.models import (
    AuditRequest,
    AuditResponse,
    ConcernType,
    EvidenceRole,
    Role,
    Verdict,
    WarningCode,
)


def _schema(name):
    return json.loads((default_contracts_dir() / name).read_text())


def _values(enum_cls):
    return [m.value for m in enum_cls]


def test_enum_drift():
    resp = _schema("audit-response.schema.json")["$defs"]
    req = _schema("audit-request.schema.json")["$defs"]
    assert _values(Verdict) == resp["Claim"]["properties"]["verdict"]["enum"]
    # Contract schema gains quantity_mismatch (13th) in Task 4 (1.2.0); until then it is a prefix.
    schema_types = resp["Concern"]["properties"]["type"]["enum"]
    assert _values(ConcernType)[: len(schema_types)] == schema_types
    assert _values(ConcernType)[len(schema_types) :] in ([], ["quantity_mismatch"])
    assert _values(EvidenceRole) == resp["Evidence"]["properties"]["role"]["enum"]
    assert _values(WarningCode) == resp["Warning"]["properties"]["code"]["enum"]
    assert _values(Role) == req["Turn"]["properties"]["role"]["enum"]


def test_request_roundtrip_and_optional_role(example_request):
    req = AuditRequest.model_validate(example_request)
    assert req.transcript[0].role is Role.interviewer
    example_request["transcript"][1].pop("role", None)
    req = AuditRequest.model_validate(example_request)
    assert req.transcript[1].role is None
    out = req.model_dump(mode="json", exclude_none=True)
    assert "role" not in out["transcript"][1]


def test_response_roundtrip_matches_contract(example_response):
    from iaudit_backend import contract

    resp = AuditResponse.model_validate(example_response)
    out = resp.model_dump(mode="json", exclude_none=True)
    # exclude_none drops explicit nulls (suggested_revision is nullable and optional)
    expected = json.loads(json.dumps(example_response))
    for c in expected["claims"]:
        if c.get("suggested_revision", 0) is None:
            del c["suggested_revision"]
    assert out == expected
    assert contract.validate_response(out) == []
