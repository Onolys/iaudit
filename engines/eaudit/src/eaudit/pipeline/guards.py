"""Useless-result guard: an empty or all-stalled audit reads like "nothing wrong", so raise.

Useful iff (a) at least one section was atomized and (b) there is no in-scope claim, or at least
one in-scope claim finished ok. A run of out-of-scope claims only is valid.
"""

from collections.abc import Collection

from eaudit.api.errors import DeadlineExceeded
from eaudit.llm import LLMUnavailable


def assess(
    sections_total: int,
    sections_ok: int,
    in_scope: int,
    in_scope_ok: int,
    reasons: Collection[str],
) -> Exception | None:
    """None if the run is useful, else the error to raise (503 / 500 / 504)."""
    if sections_total == 0:
        return None
    useful = sections_ok >= 1 and (in_scope == 0 or in_scope_ok >= 1)
    if useful:
        return None
    if "unavailable" in reasons:
        return LLMUnavailable("every unit failed: provider unavailable")
    if "error" in reasons:
        return RuntimeError("pipeline unit raised an unexpected exception")
    return DeadlineExceeded("nothing usable finished in time")
