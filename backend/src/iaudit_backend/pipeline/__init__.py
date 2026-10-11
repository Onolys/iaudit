"""Pipeline seam: the slot sub-project 06 fills."""

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any, Protocol

from iaudit_backend.api.errors import DeadlineExceeded
from iaudit_backend.config import Settings
from iaudit_backend.llm import LLMClient, MetricsCollector
from iaudit_backend.models import AuditRequest, AuditResponse, Status

MIN_CALL_S = 2.0  # below this remaining budget a stage should not start an LLM call
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
        """Per-call timeout bounded by the remaining budget; None when too little is left."""
        left = self.remaining()
        if left < MIN_CALL_S:
            return None
        return min(self.settings.llm_timeout_s, left)

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
    raise NotImplementedError("the full pipeline arrives with sub-project 06")


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
