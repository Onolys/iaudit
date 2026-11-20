"""Async LLM client used by every pipeline stage."""

import os

from .config import LLMConfig
from .errors import FixtureMiss, LLMBadOutput, LLMError, LLMTimeout, LLMUnavailable
from .fixture_client import FailingClient, FixtureClient, RecordingClient, StubClient
from .litellm_client import LiteLLMClient
from .types import LLMClient, LLMRequest, LLMResult, MetricsCollector, Usage


def make_client(settings: LLMConfig) -> LLMClient:
    if settings.llm_mode == "stub":
        return StubClient()
    if settings.llm_mode == "fixture":
        return FixtureClient(settings.fixture_dir)
    client = LiteLLMClient(settings)
    if os.environ.get("IAUDIT_LLM_RECORD") == "1":
        return RecordingClient(client, settings.fixture_dir)
    return client


__all__ = [
    "LLMConfig",
    "FailingClient",
    "FixtureClient",
    "FixtureMiss",
    "LLMBadOutput",
    "LLMClient",
    "LLMError",
    "LLMRequest",
    "LLMResult",
    "LLMTimeout",
    "LLMUnavailable",
    "LiteLLMClient",
    "MetricsCollector",
    "RecordingClient",
    "StubClient",
    "Usage",
    "make_client",
]
