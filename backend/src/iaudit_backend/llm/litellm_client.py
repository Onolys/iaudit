"""LiteLLM-backed client: JSON-schema output, own retry/timeout, global semaphore."""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import Awaitable, Callable
from typing import Any

from pydantic import ValidationError

from iaudit_backend.config import Settings

from .errors import LLMBadOutput, LLMTimeout, LLMUnavailable
from .types import LLMRequest, LLMResult, MetricsCollector, Usage

RETRY_MARGIN_S = 1.0
MAX_CACHE_PREFIXES = 2
# Errors that retrying cannot fix.
_NO_RETRY = ("AuthenticationError", "PermissionDeniedError", "NotFoundError", "BadRequestError")


def _get(obj: Any, name: str, default: Any = 0) -> Any:
    if obj is None:
        return default
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)


def _usage(resp: Any) -> Usage:
    u = _get(resp, "usage", None)
    details = _get(u, "prompt_tokens_details", None)
    cache_read = _get(u, "cache_read_input_tokens", 0) or _get(details, "cached_tokens", 0)
    return Usage(
        input_tokens=int(_get(u, "prompt_tokens", 0) or 0),
        output_tokens=int(_get(u, "completion_tokens", 0) or 0),
        cache_read_tokens=int(cache_read or 0),
        cache_write_tokens=int(_get(u, "cache_creation_input_tokens", 0) or 0),
    )


class LiteLLMClient:
    def __init__(
        self,
        settings: Settings,
        acompletion: Callable[..., Awaitable[Any]] | None = None,
    ) -> None:
        self._s = settings
        self._acompletion = acompletion
        self._sem = asyncio.Semaphore(settings.llm_max_concurrency)

    def _model(self, tier: str) -> str:
        return {
            "cheap": self._s.model_cheap,
            "mid": self._s.model_mid,
            "strong": self._s.model_strong,
        }[tier]

    def _call(self) -> Callable[..., Awaitable[Any]]:
        if self._acompletion is None:
            import litellm

            self._acompletion = litellm.acompletion
        return self._acompletion

    def _kwargs(self, req: LLMRequest, timeout_s: float) -> dict[str, Any]:
        prefixes = req.cache_prefixes or ([req.cache_prefix] if req.cache_prefix else [])
        if prefixes:
            system: Any = [
                {"type": "text", "text": p, "cache_control": {"type": "ephemeral"}}
                for p in prefixes
            ] + [{"type": "text", "text": req.system}]
        else:
            system = req.system
        return {
            "model": self._model(req.tier),
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": req.user},
            ],
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": req.response_model.__name__,
                    "schema": req.response_model.model_json_schema(),
                    "strict": True,
                },
            },
            "max_tokens": req.max_tokens,
            "temperature": req.temperature,
            "timeout": timeout_s,
            "num_retries": 0,
        }

    def _can_retry(self, req: LLMRequest, timeout_s: float) -> bool:
        if req.deadline is None:
            return True
        return req.deadline - time.monotonic() >= timeout_s + RETRY_MARGIN_S

    async def complete_json(
        self, req: LLMRequest, metrics: MetricsCollector | None = None
    ) -> LLMResult:
        if len(req.cache_prefixes) > MAX_CACHE_PREFIXES:
            raise ValueError(f"at most {MAX_CACHE_PREFIXES} cache prefixes are supported")
        timeout_s = req.timeout_s or self._s.llm_timeout_s
        model = self._model(req.tier)
        started = time.monotonic()
        attempts = 0
        usage = Usage()
        try:
            while True:
                attempts += 1
                try:
                    parsed, usage = await self._once(req, timeout_s)
                    result = LLMResult(
                        parsed=parsed,
                        usage=usage,
                        latency_ms=(time.monotonic() - started) * 1000,
                        model=model,
                        attempts=attempts,
                    )
                    self._record(
                        metrics, req, model, result.usage, result.latency_ms, attempts, True
                    )
                    return result
                except (LLMTimeout, LLMBadOutput, LLMUnavailable) as exc:
                    retryable = not getattr(exc, "no_retry", False)
                    if (
                        not retryable
                        or attempts > self._s.llm_max_retries
                        or not self._can_retry(req, timeout_s)
                    ):
                        raise
        except Exception:
            self._record(
                metrics, req, model, usage, (time.monotonic() - started) * 1000, attempts, False
            )
            raise

    @staticmethod
    def _record(metrics, req, model, usage, latency_ms, attempts, ok) -> None:
        if metrics is not None:
            metrics.record(req, model, usage, latency_ms, attempts, ok)

    async def _once(self, req: LLMRequest, timeout_s: float):
        async with self._sem:
            try:
                async with asyncio.timeout(timeout_s):
                    resp = await self._call()(**self._kwargs(req, timeout_s))
            except TimeoutError as exc:
                raise LLMTimeout("LLM call timed out") from exc
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                err = LLMUnavailable(f"LLM provider error: {type(exc).__name__}")
                err.no_retry = type(exc).__name__ in _NO_RETRY  # type: ignore[attr-defined]
                raise err from exc
        usage = _usage(resp)
        try:
            content = resp.choices[0].message.content
            parsed = req.response_model.model_validate(json.loads(content))
        except (ValueError, TypeError, AttributeError, IndexError, ValidationError) as exc:
            raise LLMBadOutput("LLM output was not valid for the schema") from exc
        return parsed, usage
