"""Settings from the SP06 env-var interface (see ../.env.example)."""

import os
from collections.abc import Mapping
from dataclasses import dataclass

from onolys_core.errors import ConfigError

ENVS = ("local", "test", "staging", "prod")
SERVICE_MODES = ("api", "worker", "combined")
ADAPTER_KINDS = ("stub", "real")
AUTH_MODES = ("fake", "idp")
LOCAL_ENVS = ("local", "test")


@dataclass(frozen=True)
class Settings:
    env: str = "test"
    service_mode: str = "combined"
    auth_mode: str = "fake"
    adapters: str = "stub"
    gcp_project: str = ""
    region: str = ""
    firestore_database: str = "(default)"
    auth_project: str = ""
    audio_bucket: str = ""
    cors_origins: tuple[str, ...] = ()
    daily_run_cap: int = 20
    max_active_runs: int = 2
    tasks_queue: str = ""
    tasks_sa: str = ""
    worker_url: str = ""
    routes_file: str = ""
    default_preset: str = ""
    git_sha: str = "dev"
    uid_hmac_key: str = ""  # keys the `uid_hash` log field (Secret Manager `uid-hmac-key-{env}`)

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> "Settings":
        e = os.environ if environ is None else environ
        env = e.get("ENV", "local")
        local = env in LOCAL_ENVS
        cap_raw = e.get("DAILY_RUN_CAP", "20")
        try:
            cap = int(cap_raw)
        except ValueError:
            raise ConfigError("DAILY_RUN_CAP must be an integer") from None
        active_raw = e.get("MAX_ACTIVE_RUNS", "2")
        try:
            max_active = int(active_raw)
        except ValueError:
            raise ConfigError("MAX_ACTIVE_RUNS must be an integer") from None
        s = cls(
            env=env,
            service_mode=e.get("SERVICE_MODE", "combined" if local else "api"),
            auth_mode=e.get("AUTH_MODE", "fake" if local else "idp"),
            adapters=e.get("ADAPTERS", "stub" if local else "real"),
            gcp_project=e.get("GCP_PROJECT", ""),
            region=e.get("REGION", ""),
            firestore_database=e.get("FIRESTORE_DATABASE", "(default)"),
            auth_project=e.get("AUTH_PROJECT", ""),
            audio_bucket=e.get("AUDIO_BUCKET", ""),
            cors_origins=tuple(
                o.strip() for o in e.get("CORS_ORIGINS", "").split(",") if o.strip()
            ),
            daily_run_cap=cap,
            max_active_runs=max_active,
            tasks_queue=e.get("TASKS_QUEUE", ""),
            tasks_sa=e.get("TASKS_SA", ""),
            worker_url=e.get("WORKER_URL", ""),
            routes_file=e.get("ROUTES_FILE", ""),
            default_preset=e.get("DEFAULT_PRESET", ""),
            git_sha=e.get("GIT_SHA", "dev"),
            uid_hmac_key=e.get("UID_HMAC_KEY", ""),
        )
        s.validate()
        return s

    def validate(self) -> None:
        for name, value, allowed in (
            ("ENV", self.env, ENVS),
            ("SERVICE_MODE", self.service_mode, SERVICE_MODES),
            ("ADAPTERS", self.adapters, ADAPTER_KINDS),
            ("AUTH_MODE", self.auth_mode, AUTH_MODES),
        ):
            if value not in allowed:
                raise ConfigError(f"{name} must be one of {', '.join(allowed)}")
        if self.auth_mode == "fake" and self.env not in LOCAL_ENVS:
            raise ConfigError("AUTH_MODE=fake is only allowed when ENV is local or test")
        if self.daily_run_cap < 0:
            raise ConfigError("DAILY_RUN_CAP must be >= 0")
        if self.max_active_runs < 0:
            raise ConfigError("MAX_ACTIVE_RUNS must be >= 0")
