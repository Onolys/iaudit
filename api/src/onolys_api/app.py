"""App factory. One codebase, SERVICE_MODE=api|worker|combined."""

import logging
import re
import time
import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from onolys_core.errors import ConfigError
from pydantic import BaseModel
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from onolys_api import logs
from onolys_api.adapters import Adapters, build_adapters
from onolys_api.audio import AudioTools, FfmpegTools
from onolys_api.auth.deps import Authenticator
from onolys_api.auth.idtoken import InvalidToken, TokenVerifier
from onolys_api.auth.oidc import OidcVerifier
from onolys_api.config import LOCAL_ENVS, Settings
from onolys_api.docs import DESCRIPTION, add_error_responses, make_docs_router
from onolys_api.errors import ApiError, ErrorDetail, ErrorResponse, error_body
from onolys_api.factory import build_blobs, build_repo
from onolys_api.jobs.delete import make_delete_handler
from onolys_api.jobs.queue import build_queue
from onolys_api.jobs.run import make_run_handler
from onolys_api.jobs.transcribe import make_poll_handler, make_transcribe_handler
from onolys_api.jobs.validate import make_validate_handler
from onolys_api.jobs.worker import HandlerSpec, TaskRunner
from onolys_api.presets import PresetResolver
from onolys_api.rating import load_schema as load_rating_schema
from onolys_api.repo.base import Repo
from onolys_api.routes import api_key as api_key_routes
from onolys_api.routes import audio as audio_routes
from onolys_api.routes import rating as rating_routes
from onolys_api.routes import runs as run_routes
from onolys_api.routes import sessions as session_routes
from onolys_api.routes import speakers as speaker_routes
from onolys_api.routes import tasks as task_routes
from onolys_api.routes import usage as usage_routes
from onolys_api.storage.base import BlobStore
from onolys_api.storage.fake import FakeBlobStore
from onolys_api.storage.fake_routes import make_fake_blob_router

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


class RequestLogMiddleware:
    """One content-free line per request: method, route template, status, latency (R10).

    Sits inside `RequestIdMiddleware` so the line carries the request id. The route is the
    template (`/v1/sessions/{id}`), never the concrete path or query string.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        start = time.perf_counter()
        status = 500

        async def send_status(message: Message) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
            await send(message)

        try:
            await self.app(scope, receive, send_status)
        finally:
            state = scope.get("state") or {}
            template = getattr(scope.get("route"), "path", None)
            if template and scope["path"].startswith("/v1/") and not template.startswith("/v1"):
                template = "/v1" + template  # FastAPI's included routers drop the outer prefix
            logs.emit(
                "request",
                method=scope.get("method"),
                route=template or "unmatched",
                status=status,
                duration_ms=round((time.perf_counter() - start) * 1000, 1),
                auth_kind=state.get("auth_kind"),
                request_id=state.get("request_id"),
            )


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
        logs.emit(
            "unhandled_exception", logging.ERROR, exc_class=type(exc).__name__,
            request_id=_rid(request),
        )  # fmt: skip
        message = "Internal server error."
        return _response(request, 500, message, [{"code": "internal_error", "message": message}])


class _RejectAllOidc:
    def verify(self, token: str) -> str:
        raise InvalidToken


class _NoQueue:
    def enqueue(self, payload, delay_s: float = 0.0) -> None:
        raise RuntimeError("TASKS_QUEUE is not configured")


def create_app(
    settings: Settings | None = None,
    repo: Repo | None = None,
    blobs: BlobStore | None = None,
    token_verifier: TokenVerifier | None = None,
    oidc_verifier: OidcVerifier | None = None,
    audio_tools: AudioTools | None = None,
    adapters: Adapters | None = None,
) -> FastAPI:
    settings = settings or Settings.from_env()
    logs.configure(settings)
    app = FastAPI(
        title="Onolys API",
        version="0.1.0",
        description=DESCRIPTION,
        openapi_url="/v1/openapi.json",
        docs_url=None,
        redoc_url=None,
    )
    app.state.settings = settings
    app.state.clock = lambda: datetime.now(UTC)  # tests replace it
    load_rating_schema()  # fail at startup, loudly, if the canonical rating schema is missing
    app.state.blobs = blobs or build_blobs(settings)
    app.state.repo = repo or build_repo(settings, app.state.blobs)
    app.state.presets = PresetResolver(settings)
    app.state.auth = Authenticator(settings, app.state.repo, token_verifier)
    queue = build_queue(settings)
    if queue is not None:
        app.state.queue = queue
    runs_tasks = settings.service_mode in ("worker", "combined")
    if runs_tasks:
        assert queue is not None or settings.service_mode == "worker"
        # worker without TASKS_QUEUE (local only): follow-up tasks have nowhere to go
        app.state.runner = TaskRunner(app.state.repo, queue or _NoQueue())
        app.state.runner.register(
            "validate",
            HandlerSpec(
                make_validate_handler(
                    app.state.blobs, audio_tools or FfmpegTools(), app.state.presets.max_audio_s
                ),
                step="validate",
            ),
        )
        app.state.adapters = adapters or build_adapters(settings)
        app.state.runner.register(
            "transcribe",
            HandlerSpec(
                make_transcribe_handler(app.state.blobs, app.state.adapters.stt, settings=settings),
                step="transcribe",
                complete=False,  # the poll that finishes the transcript marks it done
            ),
        )
        app.state.runner.register(
            "transcribe-poll",
            HandlerSpec(
                make_poll_handler(app.state.blobs, app.state.adapters.stt, settings=settings),
                step="transcribe",
                claim=False,  # the step record belongs to `transcribe`
            ),
        )
        app.state.runner.register(
            "run",
            HandlerSpec(
                make_run_handler(app.state.blobs, lambda: app.state.adapters.evaluation, settings),
                scope="run",
            ),
        )
        app.state.runner.register(
            "delete", HandlerSpec(make_delete_handler(app.state.blobs), claim=False)
        )
        if settings.env not in LOCAL_ENVS:
            if settings.worker_url and settings.tasks_sa:
                app.state.oidc = oidc_verifier or OidcVerifier(
                    settings.worker_url, settings.tasks_sa
                )
            elif settings.service_mode == "combined":
                # tasks run in process (no Cloud Tasks): /tasks/* stays mounted but trusts nobody
                app.state.oidc = _RejectAllOidc()
            else:
                raise ConfigError("WORKER_URL and TASKS_SA are required for the worker")

    app.add_middleware(
        ContractCORSMiddleware,
        allow_origins=list(settings.cors_origins),
        allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "X-API-Key", "Idempotency-Key", "Content-Type"],
        expose_headers=["X-Request-ID"],
    )
    app.add_middleware(RequestLogMiddleware)
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

    router.include_router(api_key_routes.router)
    router.include_router(session_routes.router)
    router.include_router(audio_routes.router)
    router.include_router(rating_routes.router)
    router.include_router(speaker_routes.router)
    router.include_router(run_routes.router)
    router.include_router(run_routes.runs_router)
    router.include_router(usage_routes.router)
    app.include_router(router)
    app.include_router(make_docs_router())

    def openapi_with_errors() -> dict:
        if app.openapi_schema is None:
            app.openapi_schema = add_error_responses(FastAPI.openapi(app))
        return app.openapi_schema

    app.openapi = openapi_with_errors  # type: ignore[method-assign]
    if runs_tasks:
        app.include_router(task_routes.router)  # /tasks/{kind}: Cloud Tasks only, not in schema
    if isinstance(app.state.blobs, FakeBlobStore):  # dev/tests: serve the fake signed URLs
        app.include_router(make_fake_blob_router(app.state.blobs))
    return app
