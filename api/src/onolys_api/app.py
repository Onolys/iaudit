"""App factory. One codebase, SERVICE_MODE=api|worker|combined."""

import logging
import re
import uuid

from fastapi import APIRouter, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from onolys_api.config import Settings
from onolys_api.errors import ApiError, ErrorDetail, ErrorResponse, error_body
from onolys_api.queue import InMemoryQueue

log = logging.getLogger("onolys_api")
_REQUEST_ID_OK = re.compile(r"^[A-Za-z0-9._-]{1,64}$")
ERROR_RESPONSES = {"default": {"model": ErrorResponse, "description": "Error"}}


class Healthz(BaseModel):
    status: str = "ok"
    service_mode: str
    code_version: str


class RequestIdMiddleware:
    """Honour a sane inbound X-Request-ID, else generate one; echo it on the response."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        rid = ""
        for k, v in scope["headers"]:
            if k == b"x-request-id":
                rid = v.decode("latin-1")
        if not _REQUEST_ID_OK.match(rid):
            rid = uuid.uuid4().hex
        scope.setdefault("state", {})["request_id"] = rid

        async def send_with_id(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = [(k, v) for k, v in message["headers"] if k.lower() != b"x-request-id"]
                headers.append((b"x-request-id", rid.encode()))
                message = {**message, "headers": headers}
            await send(message)

        await self.app(scope, receive, send_with_id)


class ContractCORSMiddleware(CORSMiddleware):
    """Disallowed preflights still return a contract error body."""

    def preflight_response(self, request_headers):
        resp = super().preflight_response(request_headers)
        if resp.status_code >= 400:
            return JSONResponse(
                status_code=resp.status_code,
                content=error_body(
                    resp.status_code,
                    "Cross-origin request blocked.",
                    [{"code": "cors_rejected", "message": "CORS preflight rejected."}],
                ),
            )
        return resp


def _rid(request: Request) -> str | None:
    return getattr(request.state, "request_id", None)


def _response(request: Request, status: int, message: str, details: list[ErrorDetail]):
    return JSONResponse(
        status_code=status, content=error_body(status, message, details, _rid(request))
    )


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def _api_error(request: Request, exc: ApiError):
        return _response(request, exc.status, exc.message, exc.details)

    @app.exception_handler(StarletteHTTPException)
    async def _http(request: Request, exc: StarletteHTTPException):
        known = {
            401: ("unauthenticated", "Authentication required."),
            403: ("forbidden", "Not allowed."),
            404: ("not_found", "Resource not found."),
            405: ("method_not_allowed", "Method not allowed."),
            409: ("conflict", "Conflict."),
            413: ("body_too_large", "Request body too large."),
            415: ("unsupported_media_type", "Unsupported media type."),
            429: ("rate_limited", "Too many requests."),
            503: ("upstream_unavailable", "Service temporarily unavailable."),
            504: ("deadline_exceeded", "The request ran out of time."),
        }
        if exc.status_code in known:
            code, message = known[exc.status_code]
        elif exc.status_code >= 500:
            code, message = "internal_error", "Internal server error."
        else:
            code, message = "request_rejected", "Request could not be served."
        return _response(request, exc.status_code, message, [{"code": code, "message": message}])

    @app.exception_handler(RequestValidationError)
    async def _validation(request: Request, exc: RequestValidationError):
        # paths only: pydantic messages can embed input values
        details: list[ErrorDetail] = [
            {
                "code": "invalid_parameters",
                "message": f"{'/'.join(str(p) for p in e['loc'])}: invalid parameter",
            }
            for e in exc.errors()[:5]
        ] or [{"code": "invalid_parameters", "message": "invalid parameter"}]
        return _response(request, 422, "Request rejected: invalid parameters.", details)

    @app.exception_handler(Exception)
    async def _any(request: Request, exc: Exception):
        log.error(
            "unhandled_exception exc_class=%s request_id=%s", type(exc).__name__, _rid(request)
        )
        message = "Internal server error."
        return _response(request, 500, message, [{"code": "internal_error", "message": message}])


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    app = FastAPI(
        title="Onolys API",
        version="0.1.0",
        openapi_url="/v1/openapi.json",
        docs_url=None,
        redoc_url=None,
    )
    app.state.settings = settings
    if settings.service_mode == "combined":
        app.state.queue = InMemoryQueue()  # handlers registered in Task 5

    app.add_middleware(
        ContractCORSMiddleware,
        allow_origins=list(settings.cors_origins),
        allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "X-API-Key", "Idempotency-Key", "Content-Type"],
        expose_headers=["X-Request-ID"],
    )
    app.add_middleware(RequestIdMiddleware)
    register_error_handlers(app)

    router = APIRouter(prefix="/v1")

    @router.get(
        "/healthz",
        operation_id="getHealthz",
        response_model=Healthz,
        responses=ERROR_RESPONSES,
        tags=["system"],
        summary="Liveness (no auth)",
    )
    async def healthz() -> Healthz:
        return Healthz(service_mode=settings.service_mode, code_version=settings.git_sha)

    app.include_router(router)
    return app
