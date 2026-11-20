"""SP04 T15: the public contract (AC11, AC17): docs endpoints, path rules, error models,
rating issue details, committed contract files."""

import json
import re
from pathlib import Path

import jsonschema
import pytest
from audio_helpers import A

from onolys_api import contracts, openapi
from onolys_api.errors import ErrorResponse

pytestmark = pytest.mark.unit
ROOT = Path(__file__).resolve().parents[2]
ALLOWED_PATH_PARAMS = {"id", "run_id", "report_id", "version"}


@pytest.fixture(scope="module")
def doc() -> dict:
    return json.loads(openapi.render())


def _ops(doc):
    for path, item in doc["paths"].items():
        for method, op in item.items():
            yield path, method, op


async def test_openapi_and_docs_answer_200_without_auth(client):
    r = await client.get("/v1/openapi.json")
    assert r.status_code == 200 and r.json()["openapi"].startswith("3.")
    d = await client.get("/v1/docs")
    assert d.status_code == 200 and d.headers["content-type"].startswith("text/html")
    js = await client.get("/v1/docs/redoc.standalone.js")
    assert js.status_code == 200 and "javascript" in js.headers["content-type"]
    assert len(js.content) > 500_000


async def test_docs_page_references_no_other_host(client):
    html = (await client.get("/v1/docs")).text
    assert "<script" in html
    assert not re.findall(r"https?://", html), "docs page must not name any host"
    for src in re.findall(r'(?:src|href)=["\']([^"\']+)', html):
        assert src.startswith("/v1/"), src
    assert "/v1/openapi.json" in html and "cdn" not in html.lower()


def test_openapi_is_the_committed_file(doc):
    assert (ROOT / "api/openapi.json").read_text() == openapi.render()


def test_forbidden_paths_absent_and_path_params_named(doc):
    for path in doc["paths"]:
        assert not re.match(r"^/v1/(presets|dashboard|reports)(/|$)", path), path
        for name in re.findall(r"{(\w+)}", path):
            assert name in ALLOWED_PATH_PARAMS, (path, name)
    assert "/v1/sessions/{id}/reports/{version}" in doc["paths"]
    assert "/v1/runs/{run_id}" in doc["paths"]


def test_operation_ids_unique_and_stable(doc):
    ids = [op["operationId"] for _, _, op in _ops(doc)]
    assert len(ids) == len(set(ids)) and all(re.fullmatch(r"[a-z][A-Za-z]+", i) for i in ids)


def _err_ref(op, status):
    r = op["responses"].get(status)
    assert r is not None, (op["operationId"], status, sorted(op["responses"]))
    ref = r["content"]["application/json"]["schema"]["$ref"]
    assert ref == "#/components/schemas/ErrorResponse"


EXTRA = {
    "createSession": ["409", "422"],
    "listSessions": ["422"],
    "deleteSession": ["503"],
    "requestAudioUpload": ["409", "422"],
    "completeAudioUpload": ["409", "503"],
    "confirmSpeakers": ["409", "422"],
    "putRating": ["422"],
    "startRun": ["409", "422", "429", "503"],
}


def test_every_error_status_has_an_error_model(doc):
    for path, _m, op in _ops(doc):
        if op["operationId"] == "getHealthz":
            continue
        for status in ("401", "429", "500"):
            _err_ref(op, status)
        if "{" in path:
            _err_ref(op, "404")
        for status in EXTRA.get(op["operationId"], []):
            _err_ref(op, status)
    for op in (o for _, _, o in _ops(doc)):
        assert "default" not in op["responses"], op["operationId"]


def test_idempotency_key_documented(doc):
    op = doc["paths"]["/v1/sessions"]["post"]
    (h,) = [p for p in op["parameters"] if p["name"] == "Idempotency-Key"]
    assert h["in"] == "header" and h["description"]


def test_quickstart_in_openapi_description(doc):
    desc = doc["info"]["description"]
    assert "curl" in desc and "Idempotency-Key" in desc and "/reports/" in desc


async def test_rating_invalid_details_carry_field_paths(client):
    sid = (await client.post("/v1/sessions", json={}, headers=A)).json()["session"]["id"]
    card = {
        "change_goal": "x",
        "globals": {"cct": {"score": 3, "reason": "y" * 1001}},
        "extra_key": 1,
    }
    r = await client.put(
        f"/v1/sessions/{sid}/rating", json={"final": True, "card": card}, headers=A
    )
    assert r.status_code == 422
    body = r.json()
    jsonschema.validate(
        body,
        json.loads((ROOT / "docs/contracts/public/public-error-response.schema.json").read_text()),
    )
    by_field = {d["field"]: d for d in body["details"]}
    assert by_field["globals.cct.reason"]["issue"] == "too_long"
    assert by_field["globals.cct.reason"]["code"] == "rating_invalid"
    assert by_field["$"]["issue"] == "unknown_key"
    assert "y" * 10 not in json.dumps(body)  # never card text
    # draft autosave too
    r = await client.put(
        f"/v1/sessions/{sid}/rating", json={"final": False, "card": card}, headers=A
    )
    assert r.status_code == 422
    assert r.json()["details"][0]["field"] == "globals.cct.reason"


def test_error_schema_matches_model():
    schema = json.loads(
        (ROOT / "docs/contracts/public/public-error-response.schema.json").read_text()
    )
    item = schema["properties"]["details"]["items"]["properties"]
    assert set(item) == {"code", "message", "field", "issue"}
    model = ErrorResponse.model_json_schema()["$defs"]["ErrorDetailModel"]["properties"]
    assert set(model) == set(item)


def test_contract_files_committed_and_current():
    for name, text in contracts.render_all().items():
        assert (ROOT / "docs/contracts/public" / name).read_text() == text, name
    assert {"session-detail", "create-session-request", "report-view"} <= {
        n.removesuffix(".schema.json") for n in contracts.render_all()
    }


def test_docs_and_adr_exist():
    assert (ROOT / "docs/reference/public-api.md").exists()
    assert list((ROOT / "docs/decisions").glob("0020-*.md"))
