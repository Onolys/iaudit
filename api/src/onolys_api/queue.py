"""In-memory task queue stub for SERVICE_MODE=combined (handlers are wired in Task 5)."""

from collections.abc import Awaitable, Callable
from typing import Any

Handler = Callable[[dict[str, Any]], Awaitable[None]]


class InMemoryQueue:
    def __init__(self) -> None:
        self.handlers: dict[str, Handler] = {}
        self.enqueued: list[tuple[str, dict[str, Any]]] = []

    def register(self, name: str, handler: Handler) -> None:
        self.handlers[name] = handler

    def enqueue(self, name: str, payload: dict[str, Any]) -> None:
        self.enqueued.append((name, payload))
