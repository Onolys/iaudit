"""Scaled-time latency and failure injection around a scripted client.

Every latency, deadline and cap is multiplied by one factor, so a 60 s budget becomes about a
second and the ratios hold. No new dependency.
"""

import asyncio
import random
import time

from iaudit_backend.llm import LLMResult

# per call_tag (p50, p95) seconds at factor 1
DEFAULTS = {"prep_acts": (1.5, 3), "atomize": (5, 9), "link": (4, 8), "check": (4, 8)}


class LatencyInjector:
    def __init__(self, inner, factor=1 / 50, latencies=None, failures=None, seed=7):
        self.inner = inner
        self.factor = factor
        self.latencies = latencies or DEFAULTS
        self.failures = failures or {}  # (call_tag, unit | None) -> exception
        self.rng = random.Random(seed)
        self.spans: list[tuple[str, str | None, float, float]] = []
        self.live = self.peak = 0

    def delay(self, tag: str) -> float:
        p50, p95 = self.latencies.get(tag, (0, 0))
        if not p50:
            return 0.0
        sigma = max((p95 / p50 - 1) / 1.645, 1e-6)  # lognormal with the given p50 / p95
        return p50 * self.factor * self.rng.lognormvariate(0, sigma)

    async def complete_json(self, req, metrics=None):
        start = time.monotonic()
        self.live += 1
        self.peak = max(self.peak, self.live)
        try:
            await asyncio.sleep(self.delay(req.call_tag))
            exc = self.failures.get((req.call_tag, req.unit)) or self.failures.get(
                (req.call_tag, None)
            )
            if exc is not None:
                raise exc
            res = await self.inner.complete_json(req, metrics)
            return res if isinstance(res, LLMResult) else LLMResult(parsed=res)
        finally:
            self.live -= 1
            self.spans.append((req.call_tag, req.unit, start, time.monotonic()))

    def starts(self, tag):
        return [s for t, _, s, _ in self.spans if t == tag]

    def ends(self, tag):
        return [e for t, _, _, e in self.spans if t == tag]
