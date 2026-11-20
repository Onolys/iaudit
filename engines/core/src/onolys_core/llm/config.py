"""Plain LLM settings consumed by the client. Engines build one from their own settings."""

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class LLMConfig:
    model_cheap: str = "anthropic/claude-haiku-5-5"
    model_mid: str = "anthropic/claude-sonnet-5-5"
    model_strong: str = "anthropic/claude-opus-5-5"
    llm_timeout_s: float = 30
    llm_max_retries: int = 1
    llm_max_concurrency: int = 20
    llm_mode: Literal["live", "fixture", "stub"] = "live"
    llm_response_format: Literal["json_object", "json_schema"] = "json_object"
    fixture_dir: str = "tests/fixtures/llm"
