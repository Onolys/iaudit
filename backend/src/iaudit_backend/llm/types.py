from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

from pydantic import BaseModel

Tier = Literal["cheap", "mid", "strong"]


@dataclass
class LLMRequest:
    tier: Tier
    system: str
    user: str
    response_model: type[BaseModel]
    call_tag: str
    cache_prefix: str | None = None  # stable leading text marked cacheable
    max_tokens: int = 1024
    temperature: float = 0.0
    timeout_s: float | None = None
    fixture_key: str | None = None
    deadline: float | None = None  # monotonic; gates the transport retry


@dataclass
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0


@dataclass
class LLMResult:
    parsed: Any
    usage: Usage = field(default_factory=Usage)
    latency_ms: float = 0.0
    model: str = ""
    attempts: int = 1


class MetricsCollector:
    """Append-only per-request call log. Holds no prompt or output text."""

    def __init__(self) -> None:
        self.records: list[dict[str, Any]] = []

    def record(
        self,
        req: LLMRequest,
        model: str,
        usage: Usage,
        latency_ms: float,
        attempts: int,
        ok: bool,
    ) -> None:
        self.records.append(
            {
                "call_tag": req.call_tag,
                "tier": req.tier,
                "model": model,
                "input_tokens": usage.input_tokens,
                "output_tokens": usage.output_tokens,
                "cache_read_tokens": usage.cache_read_tokens,
                "cache_write_tokens": usage.cache_write_tokens,
                "latency_ms": round(latency_ms, 1),
                "attempts": attempts,
                "ok": ok,
            }
        )

    def snapshot(self) -> dict[str, Any]:
        by_tier: dict[str, dict[str, int]] = {}
        for r in self.records:
            t = by_tier.setdefault(
                r["tier"],
                {
                    "calls": 0,
                    "input_tokens": 0,
                    "output_tokens": 0,
                    "cache_read_tokens": 0,
                    "cache_write_tokens": 0,
                },
            )
            t["calls"] += 1
            for k in ("input_tokens", "output_tokens", "cache_read_tokens", "cache_write_tokens"):
                t[k] += r[k]
        return {
            "calls": len(self.records),
            "ok": sum(1 for r in self.records if r["ok"]),
            "by_tier": by_tier,
            "records": list(self.records),
        }


class LLMClient(Protocol):
    async def complete_json(
        self, req: LLMRequest, metrics: MetricsCollector | None = None
    ) -> LLMResult: ...
