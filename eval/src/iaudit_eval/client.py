"""Audit client: one call, one classified outcome (R4, D11, D12).

Failure kinds (`Outcome.kind` when `status == "failed"`):

- ``invalid_request``: the request failed contract validation locally; nothing was sent.
- ``timeout``: total deadline (``timeout_s``) or any httpx timeout (read/write/pool
  timeout; a connect timeout is ``network``). Never retried: the backend may already have
  spent money.
- ``network``: transport failure with no HTTP response (refused, reset, DNS...). Only a
  connect error or connect timeout (``httpx.ConnectError``/``ConnectTimeout``) is
  retried once.
- ``http_error``: non-2xx status whose body is a *valid* ErrorResponse; ``error_code`` and
  ``error_message`` are set. This is the backend telling us why (rate_limited, ...).
- ``error_body``: non-2xx status whose body is non-JSON or not a valid ErrorResponse; only
  ``http_status`` (and ``issues`` when the body was JSON) are kept.
- ``invalid_response``: 2xx but the body is non-JSON or fails the response schema.
- ``request_id_mismatch``: valid response whose ``request_id`` differs from the one sent
  (checked only when the request carried one).

Retry (one, after ``backoff_s``): connect errors, 429, 502, 503. Never timeouts or 504.
Issues and log lines never contain request/response text.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

import httpx

from iaudit_eval import contracts
from iaudit_eval.contracts import Issue
from iaudit_eval.log import log_event

RETRY_STATUSES = frozenset({429, 502, 503})


@dataclass(frozen=True)
class Outcome:
    status: str  # "ok" | "failed"
    kind: str | None = None
    http_status: int | None = None
    error_code: str | None = None
    error_message: str | None = None
    issues: list[Issue] = field(default_factory=list)
    attempts: int = 0
    response: dict[str, Any] | None = None

    @property
    def ok(self) -> bool:
        return self.status == "ok"


def _failed(kind: str, attempts: int, **kw: Any) -> Outcome:
    return Outcome(status="failed", kind=kind, attempts=attempts, **kw)


class AuditClient:
    def __init__(
        self,
        base_url: str,
        timeout_s: float = 120,
        transport: httpx.AsyncBaseTransport | None = None,
        *,
        connect_timeout_s: float = 5,
        backoff_s: float = 2.0,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self.base_url = base_url
        self.timeout_s = timeout_s
        self.connect_timeout_s = connect_timeout_s
        self.backoff_s = backoff_s
        self._sleep = sleep
        self._http = httpx.AsyncClient(
            base_url=base_url,
            transport=transport,
            timeout=httpx.Timeout(timeout_s, connect=connect_timeout_s),
        )

    async def aclose(self) -> None:
        await self._http.aclose()

    async def __aenter__(self) -> AuditClient:
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.aclose()

    async def healthz(self) -> bool:
        """GET /healthz; True on 200, False on any failure."""
        try:
            async with asyncio.timeout(self.timeout_s):
                r = await self._http.get("/healthz")
        except (httpx.HTTPError, TimeoutError):
            return False
        return r.status_code == 200

    async def audit(self, request: dict[str, Any]) -> Outcome:
        issues = contracts.validate_request(request)
        if issues:
            log_event("audit_client", level=logging.WARNING, kind="invalid_request", attempt=0)
            return _failed("invalid_request", 0, issues=issues)
        attempt = 0
        while True:
            attempt += 1
            outcome, retryable = await self._once(request, attempt)
            if outcome.ok or not retryable or attempt > 1:
                log_event(
                    "audit_client",
                    status=outcome.status,
                    kind=outcome.kind or "",
                    http_status=outcome.http_status or 0,
                    attempt=attempt,
                )
                return outcome
            await self._sleep(self.backoff_s)

    async def _once(self, request: dict[str, Any], attempt: int) -> tuple[Outcome, bool]:
        """One POST. Returns (outcome, retryable)."""
        try:
            async with asyncio.timeout(self.timeout_s):
                resp = await self._http.post("/v1/audit", json=request)
        except (httpx.ConnectError, httpx.ConnectTimeout):
            return _failed("network", attempt), True
        except (httpx.TimeoutException, TimeoutError):
            return _failed("timeout", attempt), False
        except httpx.TransportError:
            return _failed("network", attempt), False

        status = resp.status_code
        try:
            body = resp.json()
        except ValueError:
            body = None
            parsed = False
        else:
            parsed = True

        if status >= 300 or status < 200:
            retryable = status in RETRY_STATUSES
            err_issues = contracts.validate_error(body) if parsed else []
            if parsed and not err_issues and body["status"] != status:
                err_issues = [Issue("status", "must equal HTTP status")]
            if parsed and not err_issues:
                return (
                    _failed(
                        "http_error",
                        attempt,
                        http_status=status,
                        error_code=body["details"][0]["code"],
                        error_message=body["message"],
                    ),
                    retryable,
                )
            return (
                _failed(
                    "error_body",
                    attempt,
                    http_status=status,
                    issues=err_issues if parsed else [],
                ),
                retryable,
            )

        if not parsed:
            return _failed("invalid_response", attempt, http_status=status), False
        resp_issues = contracts.validate_response(body)
        if resp_issues:
            out = _failed("invalid_response", attempt, http_status=status, issues=resp_issues)
            return out, False
        sent_id = request.get("request_id")
        if sent_id is not None and body.get("request_id") != sent_id:
            return _failed("request_id_mismatch", attempt, http_status=status), False
        return Outcome(status="ok", http_status=status, attempts=attempt, response=body), False
