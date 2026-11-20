"""Admin auth gate: Identity Platform ID token + email allowlist, as ASGI middleware."""

from onolys_admin_auth.config import AdminAuthConfig, ConfigError
from onolys_admin_auth.middleware import AdminAuthMiddleware
from onolys_admin_auth.verifier import IdTokenVerifier, InvalidToken, UpstreamUnavailable

__all__ = [
    "AdminAuthConfig",
    "AdminAuthMiddleware",
    "ConfigError",
    "IdTokenVerifier",
    "InvalidToken",
    "UpstreamUnavailable",
]
