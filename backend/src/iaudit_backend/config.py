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
    # Atomizer (SP03)
    atomize_max_claims: int = 30
    atomize_max_tokens: int = 4000
    atomize_retry: bool = True
    # Link (SP04)
    link_mode: Literal["auto", "whole", "shortlist"] = "auto"
    link_whole_max_tokens: int = 8000
    link_fallback_max_tokens: int = 24000
    link_top_k: int = 8
    link_correction_window: int = 4
    link_max_shortlist: int = 30
    link_max_items: int = 8
    link_max_tokens: int = 1200
    link_concurrency: int = 20
    link_retry: bool = True
    link_widen_on_empty: bool = False
    # Check (SP05)
    check_concurrency: int = 20
    check_max_tokens: int = 1500
    check_min_conf_p0: float = 0.5
    check_min_conf_p1: float = 0.6
    check_step_material: int = 1
    check_contradict_gap: int = 3
    check_rate_ratio: float = 1.5
    check_suggest_revision: bool = True
    check_retry: bool = True
    # Orchestration (SP06)
    assemble_reserve_s: float = 3
    min_call_s: float = 4
    cancel_grace_s: float = 1
    prep_soft_timeout_s: float = 10
    prep_call_timeout_s: float = 10
    atomize_call_timeout_s: float = 25
    link_call_timeout_s: float = 20
    check_call_timeout_s: float = 20
    pipeline_max_claims: int = 80
    # Misc
    log_level: str = "INFO"
    pipeline: Literal["stub", "full"] = "full"

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split_origins(cls, v):
        if isinstance(v, str):
            return [o.strip() for o in v.split(",") if o.strip()]
        return v

    def safe_summary(self) -> dict:
        """Non-secret effective config for the startup log."""
        return self.model_dump()
