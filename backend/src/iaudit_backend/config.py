"""Env-driven settings (prefix IAUDIT_). API keys are never stored here."""

from typing import Annotated, Literal

from pydantic import field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="IAUDIT_", env_file=".env", extra="ignore", frozen=True
    )

    # Limits
    max_body_bytes: int = 2_000_000
    max_turns: int = 2000
    max_sections: int = 50
    # CORS
    cors_origins: Annotated[list[str], NoDecode] = ["http://localhost:5173"]
    # Models (LiteLLM ids)
    model_cheap: str = "anthropic/claude-haiku-4-5-20251001"
    model_mid: str = "anthropic/claude-sonnet-5-5"
    model_strong: str = "anthropic/claude-opus-5-5"
    # Timeouts / retries / concurrency
    llm_timeout_s: float = 30
    audit_deadline_s: float = 60
    llm_max_retries: int = 1
    llm_max_concurrency: int = 20
    # Mode
    llm_mode: Literal["live", "fixture", "stub"] = "live"
    fixture_dir: str = "tests/fixtures/llm"
    # Assembler (SP02)
    fuzzy_threshold: float = 90
    claim_fuzzy_threshold: float = 90
    fuzzy_min_len: int = 12
    copy_ngram: int = 8
    cross_turn_slack: int = 0
    # Misc
    log_level: str = "INFO"
    pipeline: Literal["stub", "full"] = "stub"

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split_origins(cls, v):
        if isinstance(v, str):
            return [o.strip() for o in v.split(",") if o.strip()]
        return v

    def safe_summary(self) -> dict:
        """Non-secret effective config for the startup log."""
        return self.model_dump()
