"""Gateway app. Layer order (outermost first): CORS -> auth -> routes.

CORS is outermost so preflights are answered before auth (they carry no token) and
CORS headers also appear on 401/403 responses. eaudit is mounted unchanged at "/".
"""

import os
from collections.abc import Mapping
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from onolys_admin_auth import AdminAuthConfig, AdminAuthMiddleware, ConfigError

ALLOWED_HEADERS = ["authorization", "content-type"]
ALLOWED_METHODS = ["GET", "POST", "OPTIONS"]


def parse_cors_origins(raw: str) -> list[str]:
    """ADMIN_CORS_ORIGINS: comma-separated exact origins. No wildcards."""
    origins = [o.strip() for o in raw.split(",") if o.strip()]
    for o in origins:
        if "*" in o or o == "null":
            raise ConfigError("ADMIN_CORS_ORIGINS must list exact origins (no wildcards)")
    return origins


def create_app(
    eaudit_app: FastAPI | None = None,
    env: Mapping[str, str] | None = None,
    verifier=None,
) -> FastAPI:
    env = os.environ if env is None else env
    config = AdminAuthConfig.from_env(env)
    origins = parse_cors_origins(env.get("ADMIN_CORS_ORIGINS", ""))
    if eaudit_app is None:
        from eaudit.app import create_app as create_eaudit_app

        eaudit_app = create_eaudit_app()

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        # Starlette does not run a mounted app's lifespan, so run eaudit's here.
        async with eaudit_app.router.lifespan_context(eaudit_app):
            yield

    app = FastAPI(
        title="Onolys admin backend",
        lifespan=lifespan,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    app.mount("/", eaudit_app)
    # add_middleware prepends: the last one added is the outermost.
    app.add_middleware(AdminAuthMiddleware, config=config, verifier=verifier)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_methods=ALLOWED_METHODS,
        allow_headers=ALLOWED_HEADERS,
        allow_credentials=False,
    )
    return app
