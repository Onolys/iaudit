"""Admin gateway: auth middleware + CORS around the unmodified eaudit app."""

from onolys_admin_backend.app import create_app, parse_cors_origins

__all__ = ["create_app", "parse_cors_origins"]
