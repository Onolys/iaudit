"""Settings, uniform error body, Host/Origin guard, id validators, path-under-root checks."""

import os
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8100
DEFAULT_BACKEND_URL = "http://127.0.0.1:8000"
DEFAULT_ORIGINS = frozenset({"http://localhost:5173", "http://127.0.0.1:5173"})

INTERNAL_MESSAGE = "Internal error."
FORBIDDEN_MESSAGE = "Request not allowed."

DATASET_ID = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
RUN_ID = re.compile(r"^\d{8}T\d{6}Z-[a-z0-9][a-z0-9_-]{0,63}-[0-9a-f]{6}$")
ITEM_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,254}$")
_HOST = re.compile(r"^(localhost|127\.0\.0\.1)(:\d{1,5})?$")


@dataclass(frozen=True)
class Settings:
    host: str = DEFAULT_HOST
    port: int = DEFAULT_PORT
    backend_url: str = DEFAULT_BACKEND_URL
    allow_remote: bool = False
    allowed_origins: frozenset[str] = field(default=DEFAULT_ORIGINS)

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> "Settings":
        env = os.environ if env is None else env
        origins = DEFAULT_ORIGINS
        raw = env.get("IAUDIT_EVAL_ALLOWED_ORIGINS")
        if raw:
            origins = frozenset(o.strip() for o in raw.split(",") if o.strip())
        return cls(
            port=int(env.get("IAUDIT_EVAL_PORT") or DEFAULT_PORT),
            backend_url=env.get("IAUDIT_BACKEND_URL") or DEFAULT_BACKEND_URL,
            allow_remote=env.get("IAUDIT_EVAL_ALLOW_REMOTE") == "1",
            allowed_origins=origins,
        )


def validate_bind(host: str, allow_remote: bool) -> None:
    if host != DEFAULT_HOST and not allow_remote:
        raise ValueError(
            "refusing to bind a non-loopback host; set IAUDIT_EVAL_ALLOW_REMOTE=1 to override"
        )


# ---------- errors ----------

class ApiError(Exception):
    def __init__(self, code: str, status: int, message: str, detail: object = None):
        super().__init__(code)
        self.code = code
        self.status = status
        self.message = message
        self.detail = detail


def error_body(code: str, message: str, detail: object = None) -> dict:
    err: dict = {"code": code, "message": message}
    if detail is not None:
        err["detail"] = detail
    return {"error": err}


def error_response(code: str, status: int, message: str, detail: object = None) -> JSONResponse:
    return JSONResponse(status_code=status, content=error_body(code, message, detail))


def not_found(message: str = "Not found.") -> ApiError:
    return ApiError("not_found", 404, message)


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def _api(_: Request, exc: ApiError):
        return error_response(exc.code, exc.status, exc.message, exc.detail)

    @app.exception_handler(StarletteHTTPException)
    async def _http(_: Request, exc: StarletteHTTPException):
        if exc.status_code == 404:
            return error_response("not_found", 404, "Not found.")
        if exc.status_code == 403:
            return error_response("forbidden", 403, FORBIDDEN_MESSAGE)
        if exc.status_code >= 500:
            return error_response("internal_error", 500, INTERNAL_MESSAGE)
        return error_response("invalid_request", exc.status_code, "Request not accepted.")

    @app.exception_handler(RequestValidationError)
    async def _validation(_: Request, exc: RequestValidationError):
        # Locations and error types only; never echo input values.
        detail = [
            {"loc": [str(p) for p in e.get("loc", ())], "type": str(e.get("type", ""))}
            for e in exc.errors()
        ]
        return error_response("invalid_request", 422, "Invalid request.", detail)

    @app.exception_handler(Exception)
    async def _unhandled(_: Request, __: Exception):
        return error_response("internal_error", 500, INTERNAL_MESSAGE)


# ---------- Host / Origin ----------

def check_request_origin(host: str | None, origin: str | None, allowed: frozenset[str]) -> bool:
    if host is None or not _HOST.match(host):
        return False
    return origin is None or origin in allowed


# ---------- ids and paths ----------

def validate_dataset_id(value: str) -> str:
    if not isinstance(value, str) or not DATASET_ID.match(value):
        raise not_found("Dataset not found.")
    return value


def validate_run_id(value: str) -> str:
    if not isinstance(value, str) or not RUN_ID.match(value):
        raise not_found("Run not found.")
    return value


def validate_item_id(value: str, allowed: set[str] | frozenset[str]) -> str:
    """Accept only ids in the run's own item_ids that are also filename-safe."""
    if (
        not isinstance(value, str)
        or not ITEM_ID.match(value)
        or ".." in value
        or value not in allowed
    ):
        raise not_found("Item not found.")
    return value


def resolve_under(root: Path, *parts: str) -> Path:
    """Join parts below root; refuse anything resolving outside it (.., absolute, symlinks)."""
    root_r = Path(root).resolve()
    for p in parts:
        if not p or p.startswith("/") or ".." in Path(p).parts:
            raise not_found()
    target = root_r.joinpath(*parts).resolve()
    if target != root_r and root_r not in target.parents:
        raise not_found()
    return target
