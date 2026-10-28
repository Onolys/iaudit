"""Every non-2xx body is a contract error body. Messages never carry instance values."""

import logging
from typing import TypedDict

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from eaudit.contract import SCHEMA_VERSION
from eaudit.llm.errors import LLMUnavailable

log = logging.getLogger("iaudit")


class ErrorDetail(TypedDict):
    code: str
    message: str


class ApiError(Exception):
    def __init__(
        self, status: int, message: str, details: list[ErrorDetail], request_id: str | None = None
    ):
        super().__init__(message)
        self.status = status
        self.message = message
        self.details = details
        self.request_id = request_id


class DeadlineExceeded(Exception):
    """The overall audit deadline elapsed (backstop timeout or the orchestrator's own)."""


def error_body(
    status: int, message: str, details: list[ErrorDetail], request_id: str | None = None
) -> dict:
    body: dict = {
        "schema_version": SCHEMA_VERSION,
        "status": status,
        "message": message,
        "details": details,
    }
    if request_id:
        body["request_id"] = request_id
    return body


def _response(status: int, message: str, details: list[ErrorDetail], request_id: str | None = None):
    return JSONResponse(
        status_code=status, content=error_body(status, message, details, request_id)
    )


def log_exception(exc: BaseException) -> None:
    # class and frames only: exception messages may contain user data
    tb = exc.__traceback__
    frames = []
    while tb is not None:
        frames.append(f"{tb.tb_frame.f_code.co_filename.rsplit('/', 1)[-1]}:{tb.tb_lineno}")
        tb = tb.tb_next
    log.error("unhandled_exception class=%s frames=%s", type(exc).__name__, ",".join(frames[-6:]))


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def _api_error(_: Request, exc: ApiError):
        return _response(exc.status, exc.message, exc.details, exc.request_id)

    @app.exception_handler(LLMUnavailable)
    async def _unavailable(_: Request, exc: LLMUnavailable):
        message = "Audit service temporarily unavailable."
        return _response(503, message, [{"code": "upstream_unavailable", "message": message}])

    @app.exception_handler(DeadlineExceeded)
    @app.exception_handler(TimeoutError)
    async def _deadline(_: Request, exc: Exception):
        message = "The audit ran out of time."
        return _response(504, message, [{"code": "deadline_exceeded", "message": message}])

    @app.exception_handler(StarletteHTTPException)
    async def _http(_: Request, exc: StarletteHTTPException):
        if exc.status_code == 404:
            message = "Service endpoint not found."
            return _response(404, message, [{"code": "not_found", "message": message}])
        if exc.status_code == 405:
            message = "Method not allowed."
            return _response(405, message, [{"code": "method_not_allowed", "message": message}])
        if exc.status_code >= 500:
            code, message = {
                503: ("upstream_unavailable", "Audit service temporarily unavailable."),
                504: ("deadline_exceeded", "The audit ran out of time."),
            }.get(exc.status_code, ("internal_error", "Internal server error."))
            return _response(exc.status_code, message, [{"code": code, "message": message}])
        message = "Request could not be served."
        return _response(
            exc.status_code, message, [{"code": "request_rejected", "message": message}]
        )

    @app.exception_handler(RequestValidationError)
    async def _validation(_: Request, exc: RequestValidationError):
        # paths only: pydantic messages can embed input values
        details: list[ErrorDetail] = [
            {
                "code": "invalid_parameters",
                "message": f"{'/'.join(str(p) for p in e['loc'])}: invalid parameter",
            }
            for e in exc.errors()[:5]
        ]
        return _response(422, "Request rejected: invalid parameters.", details)

    @app.exception_handler(Exception)
    async def _any(_: Request, exc: Exception):
        log_exception(exc)
        message = "Internal server error."
        return _response(500, message, [{"code": "internal_error", "message": message}])
