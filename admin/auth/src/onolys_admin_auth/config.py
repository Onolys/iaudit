"""Env-driven config. Startup fails loudly on unsafe combinations."""

from collections.abc import Mapping
from dataclasses import dataclass

LOCAL_ENVS = ("local", "test")


class ConfigError(Exception):
    pass


@dataclass(frozen=True)
class AdminAuthConfig:
    enabled: bool
    project: str = ""
    allowed_emails: frozenset[str] = frozenset()

    @classmethod
    def from_env(cls, env: Mapping[str, str]) -> "AdminAuthConfig":
        """ADMIN_AUTH on|off (default: off only when ENV is explicitly local/test;
        unset or empty ENV counts as non-local, so auth is on and ADMIN_AUTH=off is refused), ENV,
        ADMIN_AUTH_PROJECT (or GCP_PROJECT), ADMIN_ALLOWED_EMAILS (comma list)."""
        env_name = (env.get("ENV") or "").strip().lower()
        mode = env.get("ADMIN_AUTH", "off" if env_name in LOCAL_ENVS else "on").strip().lower()
        if mode not in ("on", "off"):
            raise ConfigError("ADMIN_AUTH must be 'on' or 'off'")
        if mode == "off":
            if env_name not in LOCAL_ENVS:
                raise ConfigError("ADMIN_AUTH=off is only allowed when ENV is local or test")
            return cls(enabled=False)
        emails = frozenset(
            e.strip().lower() for e in env.get("ADMIN_ALLOWED_EMAILS", "").split(",") if e.strip()
        )
        if not emails:
            raise ConfigError("ADMIN_ALLOWED_EMAILS must not be empty when ADMIN_AUTH=on")
        project = (env.get("ADMIN_AUTH_PROJECT") or env.get("GCP_PROJECT") or "").strip()
        if not project:
            raise ConfigError("ADMIN_AUTH_PROJECT (or GCP_PROJECT) is required when ADMIN_AUTH=on")
        return cls(enabled=True, project=project, allowed_emails=emails)
