"""Env-driven settings (prefix IAUDIT_). API keys are never stored here."""

from typing import Annotated, Literal

from pydantic import field_validator, model_validator
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
    audit_deadline_s: float = 100
    llm_max_retries: int = 1
    llm_max_concurrency: int = 20
    # Mode
    llm_mode: Literal["live", "fixture", "stub"] = "live"
    # json_object: the prompt carries the schema and replies are validated here. json_schema asks
    # the provider for strict structured output; Haiku 5.5 often returns empty claims with it.
    llm_response_format: Literal["json_object", "json_schema"] = "json_object"
    fixture_dir: str = "tests/fixtures/llm"
    # Assembler (SP02)
    fuzzy_threshold: float = 90
    claim_fuzzy_threshold: float = 90
    fuzzy_min_len: int = 12
    copy_ngram: int = 8  # 0 turns the n-gram copy check off
    overlap_trim: bool = True  # trim the less severe of two partly overlapping claims
    cross_turn_slack: int = 0
    # Atomizer (SP03)
    atomize_max_claims: int = 30
    atomize_max_tokens: int = 16000
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
    link_per_speaker_floor: int = 2  # 0 turns the speaker floor off
    link_max_speaker_adds: int = 4
    link_later_correction_cap: int = 3  # 0 turns the later-correction pull off
    link_fusion: bool = False  # fuse BM25 with rapidfuzz by reciprocal rank
    link_rrf_k: int = 60
    link_cache_breakpoints: Literal[1, 2] = 1  # 2: transcript and stage block cached separately
    # Check (SP05)
    check_concurrency: int = 20
    check_max_tokens: int = 1500
    check_min_conf_p0: float = 0.5
    check_min_conf_p1: float = 0.6
    check_step_material: int = 1
    check_contradict_gap: int = 3
    check_rate_ratio: float = 1.5
    # confidence calibration: what low / medium / high are worth against the floors
    check_conf_low: float = 0.3
    check_conf_medium: float = 0.6
    check_conf_high: float = 0.9
    check_suggest_revision: bool = True
    check_retry: bool = True
    # Orchestration (SP06)
    assemble_reserve_s: float = 3
    min_call_s: float = 4
    cancel_grace_s: float = 1
    prep_soft_timeout_s: float = 10
    prep_llm: bool = False  # cheap-tier act tagging for unsure turns (03 optional)
    prep_chunk_turns: int = 30
    prep_context_turns: int = 3
    prep_call_timeout_s: float = 10
    atomize_call_timeout_s: float = 60
    link_call_timeout_s: float = 20
    check_call_timeout_s: float = 20
    pipeline_max_claims: int = 80
    # Cache layout and warm-up (06 optional)
    cache_layout: Literal["per_stage", "shared"] = "per_stage"
    cache_warmup: bool = False  # live mode only; needs the shared layout
    cache_min_prefix_tokens: int = 1024
    warmup_max_wait_s: float = 2
    # Misc
    log_level: str = "INFO"
    server_timing: bool = True
    pipeline: Literal["stub", "full"] = "full"

    @model_validator(mode="after")
    def _conf_values_ordered(self):
        if not self.check_conf_low <= self.check_conf_medium <= self.check_conf_high:
            raise ValueError("check_conf_low <= check_conf_medium <= check_conf_high is required")
        return self

    @property
    def check_conf_values(self) -> dict[str, float]:
        return {
            "low": self.check_conf_low,
            "medium": self.check_conf_medium,
            "high": self.check_conf_high,
        }

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split_origins(cls, v):
        if isinstance(v, str):
            return [o.strip() for o in v.split(",") if o.strip()]
        return v

    def safe_summary(self) -> dict:
        """Non-secret effective config for the startup log."""
        return self.model_dump()
