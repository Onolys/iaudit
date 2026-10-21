"""FastAPI app factory. Routes are added by later tasks; this is the guarded shell."""

import argparse
import time
from collections.abc import Sequence
from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from fastapi import FastAPI, Request

from iaudit_eval import paths
from iaudit_eval.client import AuditClient
from iaudit_eval.log import log_event
from iaudit_eval.server.guards import (
    FORBIDDEN_MESSAGE,
    INTERNAL_MESSAGE,
    Settings,
    check_request_origin,
    error_response,
    register_error_handlers,
    validate_bind,
)


def create_app(
    settings: Settings | None = None,
    backend_client=None,
    runs_root: Path | None = None,
    datasets_root: Path | None = None,
) -> FastAPI:
    settings = settings or Settings.from_env()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        owned = backend_client is None
        app.state.backend_client = AuditClient(settings.backend_url) if owned else backend_client
        try:
            yield
        finally:
            if owned:
                await app.state.backend_client.aclose()

    app = FastAPI(title="iaudit eval API", lifespan=lifespan, docs_url=None, redoc_url=None)
    app.state.settings = settings
    app.state.runs_root = Path(runs_root) if runs_root is not None else paths.runs_dir()
    app.state.datasets_root = (
        Path(datasets_root) if datasets_root is not None else paths.datasets_dir()
    )
    register_error_handlers(app)

    # No CORS middleware. Added first = inner; the logging middleware below wraps it.
    @app.middleware("http")
    async def host_origin_guard(request: Request, call_next):
        if not check_request_origin(
            request.headers.get("host"), request.headers.get("origin"), settings.allowed_origins
        ):
            return error_response("forbidden", 403, FORBIDDEN_MESSAGE)
        return await call_next(request)

    @app.middleware("http")
    async def safe_logging(request: Request, call_next):
        start = time.perf_counter()
        status = 500
        exc_class = None
        try:
            response = await call_next(request)
            status = response.status_code
        except Exception as exc:  # noqa: BLE001 - class name only is logged
            exc_class = type(exc).__name__
            response = error_response("internal_error", 500, INTERNAL_MESSAGE)
        route = getattr(request.scope.get("route"), "path", None) or "-"
        fields = {
            "method": request.method,
            "route": route,
            "http_status": status,
            "duration_ms": round((time.perf_counter() - start) * 1000),
        }
        if exc_class:
            fields["exc_class"] = exc_class
        log_event("http_request", **fields)
        return response

    return app


app = create_app()


def main(argv: Sequence[str] | None = None) -> None:
    settings = Settings.from_env()
    p = argparse.ArgumentParser(prog="iaudit-eval-server")
    p.add_argument("--host", default=settings.host)
    p.add_argument("--port", type=int, default=settings.port)
    args = p.parse_args(argv)
    validate_bind(args.host, settings.allow_remote)
    uvicorn.run(
        "iaudit_eval.server.app:app", host=args.host, port=args.port, access_log=False
    )


if __name__ == "__main__":
    main()
