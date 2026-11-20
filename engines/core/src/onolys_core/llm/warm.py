"""Prompt-cache warm-up: finish one call, then fan out the rest.

A cache entry that is still being written cannot be read, so parallel calls that share a prefix
must wait for the first call to return. Callers pass zero-argument callables (not started
coroutines) so nothing begins early. Errors propagate unchanged; a caller that treats a failed
warm call as best effort wraps its callables.
"""

import asyncio
from collections.abc import Awaitable, Callable, Sequence


async def warm_then_fanout[T, U](
    first: Callable[[], Awaitable[T]],
    rest: Sequence[Callable[[], Awaitable[U]]],
) -> tuple[T, list[U]]:
    """Await `first()`, then run every `rest` call concurrently; results follow input order."""
    warmed = await first()
    return warmed, list(await asyncio.gather(*(call() for call in rest)))
