"""An outcome-driven retry loop with caller-owned retry decisions."""

import asyncio
import math
from collections.abc import Awaitable, Callable


async def retry[T](
    fn: Callable[[int], Awaitable[T]],
    *,
    should_retry: Callable[[T | BaseException], bool],
    attempts: int = 2,
    delay: float = 0.0,
    backoff: float = 1.0,
    can_continue: Callable[[], bool] | None = None,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> T:
    """Call ``fn`` with 1-based attempts, returning or raising its final outcome.

    ``can_continue`` gates retries only; the first attempt always runs.
    Cancellation propagates immediately, including during the injected sleep.
    """
    if isinstance(attempts, bool) or not isinstance(attempts, int) or attempts < 1:
        raise ValueError("attempts must be a positive integer")
    if not math.isfinite(delay) or delay < 0:
        raise ValueError("delay must be finite and nonnegative")
    if not math.isfinite(backoff) or backoff < 0:
        raise ValueError("backoff must be finite and nonnegative")

    for attempt in range(1, attempts + 1):
        error: BaseException | None = None
        try:
            value = await fn(attempt)
            outcome: T | BaseException = value
        except asyncio.CancelledError:
            raise
        except BaseException as exc:
            error = exc
            outcome = exc

        again = should_retry(outcome)
        if not again or attempt == attempts or (can_continue is not None and not can_continue()):
            if error is not None:
                raise error
            return value
        await sleep(delay * backoff ** (attempt - 1))

    raise AssertionError("positive attempts must produce an outcome")
