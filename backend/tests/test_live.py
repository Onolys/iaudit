"""Opt-in live check of the model ids: IAUDIT_LIVE=1 ANTHROPIC_API_KEY=... uv run pytest -m live"""

import os

import pytest
from pydantic import BaseModel

from iaudit_backend.config import Settings
from iaudit_backend.llm import LiteLLMClient, LLMRequest, MetricsCollector

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(
        not (os.environ.get("IAUDIT_LIVE") == "1" and os.environ.get("ANTHROPIC_API_KEY")),
        reason="set IAUDIT_LIVE=1 and ANTHROPIC_API_KEY to run live calls",
    ),
]


class Pong(BaseModel):
    word: str
    number: int


@pytest.mark.parametrize("tier", ["cheap", "mid"])
async def test_tier_returns_schema_valid_json(tier):
    metrics = MetricsCollector()
    res = await LiteLLMClient(Settings(llm_mode="live")).complete_json(
        LLMRequest(
            tier=tier,
            system="Reply with the requested JSON only.",
            user='Return word "pong" and number 7.',
            response_model=Pong,
            call_tag="live-check",
            max_tokens=100,
            timeout_s=60,
        ),
        metrics,
    )
    assert isinstance(res.parsed, Pong)
    assert res.usage.input_tokens > 0
    print(tier, res.model, res.usage, res.latency_ms)
