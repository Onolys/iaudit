"""In-process fake of the audit backend for tests (httpx.MockTransport).

Serves GET /healthz and POST /v1/audit. Default responses are schema-valid
AuditResponses (contract 0.0.1 with run_info) derived deterministically from the
request: one `insufficient_evidence` claim per assessment section. Switch behaviour
with `mode` (all requests) or `script` (per-request modes consumed in order, then
`mode`). Offline only.

Modes: ok, 429, 500, 503, 504, timeout, bad_body, invalid_error_body, mismatched_id,
missing_cost, changed_models, changed_prompts, invalid_request.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import httpx

from iaudit_eval import contracts

MODES = {
    "ok", "429", "500", "503", "504", "timeout", "bad_body", "invalid_error_body",
    "mismatched_id", "missing_cost", "changed_models", "changed_prompts",
    "invalid_request",
}  # fmt: skip

_ERRORS = {
    "429": (429, "rate_limited", "Too many requests."),
    "500": (500, "internal_error", "Internal error."),
    "503": (503, "upstream_unavailable", "Service unavailable."),
    "504": (504, "deadline_exceeded", "Gateway timeout."),
}

BASE_MODELS = {"cheap": "fake-cheap-1", "mid": "fake-mid-1", "strong": "fake-strong-1"}
BASE_HASHES = {
    "atomize": "0123456789abcdef",
    "link": "fedcba9876543210",
    "check": "00112233445566ff",
    "prep": "a1b2c3d4e5f60718",
}


class FakeBackend:
    def __init__(
        self,
        mode: str = "ok",
        *,
        script: list[str] | None = None,
        delay: float = 0.0,
        supported_version: str | None = None,
        retry_after: str | None = None,
        cost_usd: float = 0.01,
    ) -> None:
        self._check_mode(mode)
        for m in script or []:
            self._check_mode(m)
        self.mode = mode
        self.script = list(script or [])
        self.delay = delay
        self.supported_version = supported_version or contracts.schema_version()
        self.retry_after = retry_after
        self.cost_usd = cost_usd
        self.count = 0  # POST /v1/audit requests received
        self.audit_work = 0  # responses built (real audit work); probes must leave it 0
        self.in_flight = 0
        self.max_in_flight = 0
        self.requests: list[httpx.Request] = []

    @staticmethod
    def _check_mode(mode: str) -> None:
        if mode not in MODES:
            raise ValueError(f"unknown fake backend mode: {mode}")

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handle)

    async def handle(self, request: httpx.Request) -> httpx.Response:
        if request.method == "GET" and request.url.path == "/healthz":
            return httpx.Response(200, json={"status": "ok"})
        if request.method == "POST" and request.url.path == "/v1/audit":
            return await self._audit(request)
        return httpx.Response(404, json=self._error(404, "not_found", "Not found."))

    def _error(self, status: int, code: str, message: str, request_id: str | None = None) -> dict[str, Any]:
        body: dict[str, Any] = {"schema_version": self.supported_version}
        if request_id:
            body["request_id"] = request_id
        body.update(status=status, message=message, details=[{"code": code, "message": message}])
        return body

    async def _audit(self, request: httpx.Request) -> httpx.Response:
        self.count += 1
        self.requests.append(request)
        mode = self.script.pop(0) if self.script else self.mode
        self.in_flight += 1
        self.max_in_flight = max(self.max_in_flight, self.in_flight)
        try:
            if self.delay:
                await asyncio.sleep(self.delay)
            return self._respond(request, mode)
        finally:
            self.in_flight -= 1

    def _respond(self, request: httpx.Request, mode: str) -> httpx.Response:
        if mode == "timeout":
            raise httpx.ReadTimeout("fake read timeout", request=request)
        try:
            raw = json.loads(request.content)
        except ValueError:
            raw = None
        if not isinstance(raw, dict):
            return httpx.Response(400, json=self._error(400, "invalid_json", "Body is not JSON."))
        rid = raw.get("request_id")
        rid = rid if isinstance(rid, str) and rid else None

        if mode == "invalid_request":
            return httpx.Response(
                400, json=self._error(400, "schema_violation", "Request does not match the contract.", rid)
            )
        if mode in _ERRORS:
            status, code, msg = _ERRORS[mode]
            headers = {"Retry-After": self.retry_after} if self.retry_after else None
            return httpx.Response(status, json=self._error(status, code, msg, rid), headers=headers)
        if mode == "invalid_error_body":
            return httpx.Response(500, json={"oops": "not an error body"})
        if contracts.validate_request(raw):
            return httpx.Response(
                400,
                json=self._error(400, "schema_violation", "Request does not match the contract.", rid),
            )
        if mode == "bad_body":
            return httpx.Response(200, content=b"<html>not json</html>")

        body = self.build_response(raw, mode)
        return httpx.Response(200, json=body)

    def build_response(self, raw: dict[str, Any], mode: str = "ok") -> dict[str, Any]:
        self.audit_work += 1
        models = dict(BASE_MODELS)
        hashes = dict(BASE_HASHES)
        if mode == "changed_models":
            models["strong"] = "fake-strong-2"
        if mode == "changed_prompts":
            hashes["check"] = "ffeeddccbbaa9988"
        run_info: dict[str, Any] = {
            "models": models,
            "prompt_hashes": hashes,
            "input_tokens": 100,
            "output_tokens": 20,
            "cache_read_tokens": 0,
            "cache_write_tokens": 0,
        }
        if mode != "missing_cost":
            run_info["cost_usd"] = self.cost_usd
        claims = []
        for i, sec in enumerate(raw.get("assessment", [])):
            text = sec.get("text", "") if isinstance(sec, dict) else ""
            claims.append(
                {
                    "id": f"c{i}",
                    "span": {
                        "start": {"index": i, "char": 0},
                        "end": {"index": i, "char": len(text)},
                    },
                    "verdict": "insufficient_evidence",
                    "explanation": "Fake backend: no evidence assessed.",
                    "suggested_revision": None,
                    "concerns": [],
                    "evidence": [],
                }
            )
        body: dict[str, Any] = {
            "schema_version": self.supported_version,
            "status": "complete",
            "warnings": [],
            "claims": claims,
            "run_info": run_info,
        }
        rid = raw.get("request_id")
        if isinstance(rid, str) and rid:
            body["request_id"] = "other-" + rid if mode == "mismatched_id" else rid
        elif mode == "mismatched_id":
            body["request_id"] = "other-id"
        return body
