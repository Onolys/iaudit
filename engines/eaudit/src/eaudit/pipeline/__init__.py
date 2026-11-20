"""Pipeline seam: the slot sub-project 06 fills."""

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any, Protocol

from eaudit.api.errors import DeadlineExceeded
from eaudit.config import Settings
from eaudit.llm import LLMClient, MetricsCollector
from eaudit.models import AuditRequest, AuditResponse, Status

MIN_CALL_S = 4.0  # default of Settings.min_call_s: below this remaining budget no call starts
BACKSTOP_GRACE_S = 2.0


@dataclass
class RequestContext:
    settings: Settings
    llm: LLMClient
    metrics: MetricsCollector
    request_id: str | None
    deadline: float  # time.monotonic()
    log: Any = None
    extras: dict = field(default_factory=dict)

    def remaining(self) -> float:
        return max(0.0, self.deadline - time.monotonic())

    def call_timeout(self, stage: str) -> float | None:
        """Per-call timeout: the stage cap (llm_timeout_s if none), bounded by the remaining budget.

        None when too little is left.
        """
        left = self.remaining()
        if left < self.settings.min_call_s:
            return None
        cap = getattr(self.settings, f"{stage}_call_timeout_s", self.settings.llm_timeout_s)
        return min(cap, left)

    @property
    def fixture_scope(self) -> str | None:
        return self.request_id


class Pipeline(Protocol):
    async def run(self, req: AuditRequest, ctx: RequestContext) -> AuditResponse: ...


class StubPipeline:
    """A valid empty audit: no claims, status complete."""

    async def run(self, req: AuditRequest, ctx: RequestContext) -> AuditResponse:
        return AuditResponse(
            request_id=req.request_id, status=Status.complete, warnings=[], claims=[]
        )


def make_pipeline(settings: Settings) -> Pipeline:
    if settings.pipeline == "stub":
        return StubPipeline()
    from .full import FullPipeline  # imported here: full.py imports this module

    return FullPipeline()


async def run_with_backstop(
    pipeline: Pipeline,
    req: AuditRequest,
    ctx: RequestContext,
    settings: Settings,
    grace_s: float = BACKSTOP_GRACE_S,
) -> AuditResponse:
    """Hard overall timeout. 06 does graceful partials inside it; this only guards the cap."""
    try:
        async with asyncio.timeout(settings.audit_deadline_s + grace_s):
            return await pipeline.run(req, ctx)
    except TimeoutError as exc:
        raise DeadlineExceeded("audit deadline exceeded") from exc
