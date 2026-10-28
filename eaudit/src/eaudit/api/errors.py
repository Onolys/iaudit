"""Every non-2xx body is a contract error body. Messages never carry instance values."""

import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from eaudit.contract import SCHEMA_VERSION
from eaudit.llm.errors import LLMUnavailable

log = logging.getLogger("iaudit")


class ApiError(Exception):
    def __init__(self, code: str, message: str, status: int, request_id: str | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status
        self.request_id = request_id


class DeadlineExceeded(Exception):
    """The overall audit deadline elapsed (backstop timeout or the orchestrator's own)."""


def error_body(code: str, message: str, request_id: str | None = None) -> dict:
    body: dict = {"schema_version": SCHEMA_VERSION}
    if request_id:
        body["request_id"] = request_id
    body["error"] = {"code": code, "message": message}
    return body


def _response(status: int, code: str, message: str, request_id: str | None = None):
    return JSONResponse(status_code=status, content=error_body(code, message, request_id))


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
        return _response(exc.status, exc.code, exc.message, exc.request_id)

    @app.exception_handler(LLMUnavailable)
    async def _unavailable(_: Request, exc: LLMUnavailable):
        return _response(503, "unavailable", "The audit service is temporarily unavailable.")

    @app.exception_handler(DeadlineExceeded)
    @app.exception_handler(TimeoutError)
    async def _deadline(_: Request, exc: Exception):
        return _response(504, "unavailable", "The audit could not produce a usable result.")

    @app.exception_handler(StarletteHTTPException)
    async def _http(_: Request, exc: StarletteHTTPException):
        if exc.status_code == 404:
            return _response(404, "other", "Not found.")
        if exc.status_code == 405:
            return _response(405, "other", "Method not allowed.")
        return _response(exc.status_code, "other", "Request could not be served.")

    @app.exception_handler(RequestValidationError)
    async def _validation(_: Request, exc: RequestValidationError):
        # paths only: pydantic messages can embed input values
        locs = ", ".join("/".join(str(p) for p in e["loc"]) for e in exc.errors()[:5])
        return _response(422, "invalid_request", f"Invalid request parameters: {locs}.")

    @app.exception_handler(Exception)
    async def _any(_: Request, exc: Exception):
        log_exception(exc)
        return _response(500, "internal_error", "Internal server error.")
