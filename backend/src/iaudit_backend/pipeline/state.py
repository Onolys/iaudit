"""Write-once run state. Flows write results here; the supervisor reads them after cancelling.

No TaskGroup: one bug-induced exception would cancel siblings and lose finished work. Waits go
through events, never `await task`, so cancelling one flow cannot cancel a task others share.
"""

import asyncio
import contextlib
import logging
import time
from collections.abc import Callable, Coroutine, Iterator
from dataclasses import dataclass, field
from typing import Any

from iaudit_backend.assembler.models import ClaimDraft
from iaudit_backend.atomize.models import AtomicClaim, SectionAtoms
from iaudit_backend.prep import PrepResult

log = logging.getLogger("iaudit")


@dataclass
class RunState:
    prep_ready: asyncio.Event = field(default_factory=asyncio.Event)
    idle: asyncio.Event = field(default_factory=asyncio.Event)
    prep: PrepResult | None = None
    link_ctx: Any = None  # built once, after prep is ready
    atoms: dict[int, SectionAtoms] = field(default_factory=dict)
    admitted: dict[str, AtomicClaim] = field(default_factory=dict)  # claim id -> claim, in order
    drafts: dict[str, ClaimDraft] = field(default_factory=dict)
    errored_claims: dict[str, str] = field(default_factory=dict)  # claim id -> exception class
    errored_sections: dict[int, str] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)  # exception class names only
    truncated: bool = False
    deadline_hit: bool = False
    cancelled: int = 0
    tasks: set[asyncio.Task] = field(default_factory=set)
    outstanding: int = 0
    spans: dict[str, list[float]] = field(default_factory=dict)  # stage -> [first start, last end]

    def __post_init__(self) -> None:
        self.idle.set()

    # -- write-once results -------------------------------------------------------------
    def write_atoms(self, index: int, atoms: SectionAtoms) -> None:
        self.atoms.setdefault(index, atoms)

    def write_draft(self, claim_id: str, draft: ClaimDraft) -> None:
        self.drafts.setdefault(claim_id, draft)

    # -- tasks ------------------------------------------------------------------------------
    def spawn(
        self,
        make: Callable[[], Coroutine[Any, Any, None]],
        *,
        claim_id: str | None = None,
        section: int | None = None,
    ) -> asyncio.Task:
        """Run `make()` as a tracked task. Unexpected exceptions are recorded, never raised;
        CancelledError is not caught."""

        async def run() -> None:
            try:
                await make()
            except Exception as exc:  # noqa: BLE001 - recorded by class name only
                name = type(exc).__name__
                self.errors.append(name)
                if claim_id is not None:
                    self.errored_claims[claim_id] = name
                if section is not None:
                    self.errored_sections[section] = name
                log.error("pipeline_unit_failed class=%s", name)

        task = asyncio.create_task(run())
        self.tasks.add(task)
        self.outstanding += 1
        self.idle.clear()
        task.add_done_callback(self._done)
        return task

    def _done(self, task: asyncio.Task) -> None:
        self.tasks.discard(task)
        self.outstanding -= 1
        if self.outstanding == 0:
            self.idle.set()

    async def cancel_all(self, grace_s: float) -> None:
        live = [t for t in self.tasks if not t.done()]
        self.cancelled += len(live)
        for t in live:
            t.cancel()
        if live:
            await asyncio.wait(live, timeout=grace_s)

    # -- observability ----------------------------------------------------------------------
    @contextlib.contextmanager
    def span(self, stage: str) -> Iterator[None]:
        start = time.monotonic()
        try:
            yield
        finally:
            end = time.monotonic()
            s = self.spans.setdefault(stage, [start, end])
            s[0], s[1] = min(s[0], start), max(s[1], end)
