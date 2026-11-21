"""LiteLLM-backed client: route-driven kwargs, retries, rate-limit backoff, per-route semaphore."""

from __future__ import annotations

import asyncio
import json
import random
import re
import sys
import time
from collections.abc import Awaitable, Callable
from typing import Any

from pydantic import ValidationError

from onolys_core.errors import ConfigError
from onolys_core.retry import retry

from .config import LLMConfig
from .errors import LLMBadOutput, LLMRateLimited, LLMTimeout, LLMUnavailable
from .routes import Route, resolve_preset
from .types import LLMRequest, LLMResult, MetricsCollector, Usage

RETRY_MARGIN_S = 1.0
MAX_CACHE_PREFIXES = 2
# Errors that retrying cannot fix.
_NO_RETRY = ("AuthenticationError", "PermissionDeniedError", "NotFoundError", "BadRequestError")


_FENCE = re.compile(r"^\s*```(?:json)?\s*(.*?)\s*```\s*$", re.DOTALL)


def _unfence(text: str) -> str:
    """Some models wrap JSON replies in a markdown fence even when asked for a bare object."""
    m = _FENCE.match(text)
    return m.group(1) if m else text


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


def _kind(exc: BaseException | None) -> str:
    if isinstance(exc, LLMTimeout):
        return "timeout"
    if isinstance(exc, LLMBadOutput):
        return "bad_output"
    if isinstance(exc, LLMRateLimited):
        return "rate_limited"
    if isinstance(exc, LLMUnavailable):
        return "unavailable"
    return "error"


def _status(exc: BaseException) -> int | None:
    code = getattr(exc, "status_code", None)
    if code is None:
        code = getattr(getattr(exc, "response", None), "status_code", None)
    return code if isinstance(code, int) else None


def _is_rate_limit(exc: BaseException) -> bool:
    return _status(exc) in (429, 529) or type(exc).__name__ == "RateLimitError"


def _retry_after(exc: BaseException) -> float | None:
    """Seconds from a `retry-after` header (numeric form only), wherever the exception keeps it."""
    holders = (
        getattr(getattr(exc, "response", None), "headers", None),
        getattr(exc, "litellm_response_headers", None),
        getattr(exc, "headers", None),
    )
    for h in holders:
        if not h:
            continue
        try:
            raw = h.get("retry-after") or h.get("Retry-After")
            if raw is not None:
                value = float(raw)
                if value >= 0:
                    return value
        except (AttributeError, TypeError, ValueError):
            continue
    return None


class LiteLLMClient:
    """Every limit and provider quirk is read from the request's route (see routes.py)."""

    def __init__(
        self,
        settings: LLMConfig,
        acompletion: Callable[..., Awaitable[Any]] | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._s = settings
        self._acompletion = acompletion
        self._sleep = sleep
        self.routes: dict[str, Route] = (
            dict(settings.routes)
            if settings.routes is not None
            else resolve_preset(settings.preset)[0]
        )
        self._sems: dict[str, asyncio.Semaphore] = {}

    def _route(self, name: str) -> Route:
        try:
            return self.routes[name]
        except KeyError:
            raise ConfigError(f"unknown LLM route {name!r}") from None

    def _sem(self, name: str) -> asyncio.Semaphore:
        """One semaphore per route, sized by the route's max_concurrency."""
        sem = self._sems.get(name)
        if sem is None:
            sem = self._sems[name] = asyncio.Semaphore(self._route(name).max_concurrency)
        return sem

    def _call(self) -> Callable[..., Awaitable[Any]]:
        if self._acompletion is None:
            import litellm

            self._acompletion = litellm.acompletion
        return self._acompletion

    @staticmethod
    def _response_format(route: Route, req: LLMRequest) -> dict[str, Any]:
        if route.structured_output_mode == "json_object":
            return {"type": "json_object"}
        return {
            "type": "json_schema",
            "json_schema": {
                "name": req.response_model.__name__,
                "schema": req.response_model.model_json_schema(),
                "strict": True,
            },
        }

    @staticmethod
    def _system(route: Route, req: LLMRequest, prefixes: list[str]) -> Any:
        if not prefixes:
            return req.system
        if route.caching_mode == "anthropic_ephemeral":
            return [
                {"type": "text", "text": p, "cache_control": {"type": "ephemeral"}}
                for p in prefixes
            ] + [{"type": "text", "text": req.system}]
        return "\n\n".join([*prefixes, req.system])

    @staticmethod
    def _limits(route: Route, req: LLMRequest) -> tuple[int, float]:
        """(max_tokens, timeout_s): the request's value, or the route's; never above the route's."""
        max_tokens = min(req.max_tokens or route.max_output_tokens, route.max_output_tokens)
        timeout_s = min(req.timeout_s or route.timeout_s, route.timeout_s)
        return max_tokens, timeout_s

    def _kwargs(self, req: LLMRequest, timeout_s: float) -> dict[str, Any]:
        route = self._route(req.tier)
        prefixes = req.cache_prefixes or ([req.cache_prefix] if req.cache_prefix else [])
        kwargs: dict[str, Any] = {
            "model": route.litellm_id,
            "messages": [
                {"role": "system", "content": self._system(route, req, prefixes)},
                {"role": "user", "content": req.user},
            ],
            "response_format": self._response_format(route, req),
            "max_tokens": self._limits(route, req)[0],
            "timeout": timeout_s,
            "drop_params": True,
            "num_retries": 0,
        }
        if route.supports_temperature:
            kwargs["temperature"] = req.temperature
        kwargs.update(route.extra_params)  # provider quirks live in the route, not in code
        return kwargs

    def _can_retry(self, req: LLMRequest, timeout_s: float) -> bool:
        if req.deadline is None:
            return True
        return req.deadline - time.monotonic() >= timeout_s + RETRY_MARGIN_S

    async def complete_json(
        self, req: LLMRequest, metrics: MetricsCollector | None = None
    ) -> LLMResult:
        if len(req.cache_prefixes) > MAX_CACHE_PREFIXES:
            raise ValueError(f"at most {MAX_CACHE_PREFIXES} cache prefixes are supported")
        route = self._route(req.tier)
        timeout_s = self._limits(route, req)[1]
        model = route.litellm_id
        started = time.monotonic()
        attempts = 0
        usage = Usage()

        async def call(attempt: int):
            nonlocal attempts, usage
            attempts = attempt
            parsed, usage = await self._once_rate_limited(req, route, timeout_s, started)
            return parsed

        try:
            parsed = await retry(
                call,
                attempts=1 + route.max_retries if req.retry else 1,
                delay=route.backoff_s,
                backoff=2.0,
                should_retry=lambda outcome: (
                    isinstance(outcome, (LLMTimeout, LLMBadOutput, LLMUnavailable))
                    and not getattr(outcome, "no_retry", False)
                ),
                can_continue=lambda: self._can_retry(req, timeout_s),
            )
            result = LLMResult(
                parsed=parsed,
                usage=usage,
                latency_ms=(time.monotonic() - started) * 1000,
                model=model,
                attempts=attempts,
            )
            self._record(metrics, req, model, result.usage, result.latency_ms, attempts, True)
            return result
        except Exception:
            self._record(
                metrics, req, model, usage, (time.monotonic() - started) * 1000, attempts, False,
                _kind(sys.exc_info()[1]),
            )  # fmt: skip
            raise

    @staticmethod
    def _record(metrics, req, model, usage, latency_ms, attempts, ok, error_kind=None) -> None:
        if metrics is not None:
            metrics.record(req, model, usage, latency_ms, attempts, ok, error_kind)

    async def _once_rate_limited(
        self, req: LLMRequest, route: Route, timeout_s: float, started: float
    ):
        """One attempt, re-sent after a 429/529 for as long as the deadline allows.

        Rate-limit waits do not use the route's max_retries. With no request deadline the
        budget is one route timeout from the start of the call. The wait happens outside the
        semaphore, so a backing-off call does not hold a slot.
        """
        limit = req.deadline if req.deadline is not None else started + route.timeout_s
        waits = 0
        while True:
            try:
                return await self._once(req, route, timeout_s)
            except LLMRateLimited as exc:
                backoff = route.backoff_s * 2**waits * random.uniform(0.5, 1.0)
                wait = max(exc.retry_after or 0.0, backoff)
                if time.monotonic() + wait + RETRY_MARGIN_S > limit:
                    exc.no_retry = True  # type: ignore[attr-defined]
                    raise
                waits += 1
                await self._sleep(wait)

    async def _once(self, req: LLMRequest, route: Route, timeout_s: float):
        async with self._sem(req.tier):
            try:
                async with asyncio.timeout(timeout_s):
                    resp = await self._call()(**self._kwargs(req, timeout_s))
            except TimeoutError as exc:
                raise LLMTimeout("LLM call timed out") from exc
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                if _is_rate_limit(exc):
                    raise LLMRateLimited(
                        f"LLM provider rate limited ({_status(exc) or type(exc).__name__})",
                        retry_after=_retry_after(exc),
                    ) from exc
                err = LLMUnavailable(f"LLM provider error: {type(exc).__name__}")
                err.no_retry = type(exc).__name__ in _NO_RETRY  # type: ignore[attr-defined]
                raise err from exc
        usage = _usage(resp)
        try:
            if _get(resp.choices[0], "finish_reason", None) == "length":
                trunc = LLMBadOutput("LLM output cut off at the token limit")
                trunc.no_retry = True  # type: ignore[attr-defined]
                raise trunc
            content = resp.choices[0].message.content
            parsed = req.response_model.model_validate(json.loads(_unfence(content)))
        except LLMBadOutput:
            raise
        except (ValueError, TypeError, AttributeError, IndexError, ValidationError) as exc:
            raise LLMBadOutput("LLM output was not valid for the schema") from exc
        return parsed, usage
