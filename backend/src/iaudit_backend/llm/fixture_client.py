"""No-network clients: hash-keyed fixture replay, in-code stub, and a failing client."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from .errors import FixtureMiss
from .types import LLMRequest, LLMResult, MetricsCollector, Usage

_SAFE_KEY = re.compile(r"^[A-Za-z0-9._-]+$")


class FixtureClient:
    def __init__(self, fixture_dir: str | Path) -> None:
        self._dir = Path(fixture_dir)

    @staticmethod
    def key_for(req: LLMRequest) -> str:
        canonical = json.dumps(
            {
                "tier": req.tier,
                "call_tag": req.call_tag,
                "system": req.system,
                "user": req.user,
                "cache_prefix": req.cache_prefix,
                "schema": req.response_model.__name__,
            },
            sort_keys=True,
            ensure_ascii=False,
        )
        return hashlib.sha256(f"{req.tier}|{req.call_tag}|{canonical}".encode()).hexdigest()

    async def complete_json(
        self, req: LLMRequest, metrics: MetricsCollector | None = None
    ) -> LLMResult:
        key = req.fixture_key or self.key_for(req)
        if not _SAFE_KEY.match(key):
            raise FixtureMiss("invalid fixture key")
        path = self._dir / f"{key}.json"
        if not path.is_file():
            raise FixtureMiss(f"no fixture for key {key} (call_tag={req.call_tag})")
        parsed = req.response_model.model_validate(json.loads(path.read_text(encoding="utf-8")))
        if metrics is not None:
            metrics.record(req, "fixture", Usage(), 0.0, 1, True)
        return LLMResult(parsed=parsed, model="fixture")


class StubClient:
    """Returns a canned object (or callable(req) result) registered per call_tag."""

    def __init__(self) -> None:
        self._canned: dict[str, Any] = {}

    def register(
        self, call_tag: str, value: BaseModel | dict | Callable[[LLMRequest], Any]
    ) -> None:
        self._canned[call_tag] = value

    async def complete_json(
        self, req: LLMRequest, metrics: MetricsCollector | None = None
    ) -> LLMResult:
        if req.call_tag not in self._canned:
            raise FixtureMiss(f"no stub registered for call_tag {req.call_tag}")
        value = self._canned[req.call_tag]
        if callable(value):
            value = value(req)
        if isinstance(value, dict):
            value = req.response_model.model_validate(value)
        if metrics is not None:
            metrics.record(req, "stub", Usage(), 0.0, 1, True)
        return LLMResult(parsed=value, model="stub")


class FailingClient:
    def __init__(self, exc: BaseException) -> None:
        self._exc = exc

    async def complete_json(
        self, req: LLMRequest, metrics: MetricsCollector | None = None
    ) -> LLMResult:
        if metrics is not None:
            metrics.record(req, "failing", Usage(), 0.0, 1, False)
        raise self._exc


class RecordingClient:
    """Opt-in (IAUDIT_LLM_RECORD=1): wraps a live client and writes fixtures for replay."""

    def __init__(self, inner, fixture_dir: str | Path) -> None:
        self._inner = inner
        self._dir = Path(fixture_dir)

    async def complete_json(
        self, req: LLMRequest, metrics: MetricsCollector | None = None
    ) -> LLMResult:
        res = await self._inner.complete_json(req, metrics)
        key = req.fixture_key or FixtureClient.key_for(req)
        if _SAFE_KEY.match(key):
            self._dir.mkdir(parents=True, exist_ok=True)
            (self._dir / f"{key}.json").write_text(res.parsed.model_dump_json(), encoding="utf-8")
        return res
