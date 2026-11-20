"""Spend guard (R8, D14): daily run cap + concurrent active-run limit.

Call `reserve_run` where a run is created (auto-start R4, `POST /runs`): it atomically checks
both limits and counts the run, or raises 429 `daily_cap_reached` (the code for both causes: at
auto-start the session then stays `awaiting_input` with that `error_code`, D14). Every reserved
run must later be released exactly once with `release_run`: `refund=True` when it failed before
any LLM call (gives the daily count back), `refund=False` when it ended after spending.
"""

from datetime import UTC, datetime, timedelta

from onolys_api.config import Settings
from onolys_api.errors import ApiError
from onolys_api.repo.base import Repo

DAILY_MESSAGE = "Daily run limit reached."
CONCURRENT_MESSAGE = "Too many runs in progress."


def utc_date(now: datetime | None = None) -> str:
    return (now or datetime.now(UTC)).astimezone(UTC).strftime("%Y-%m-%d")


def resets_at(now: datetime | None = None) -> datetime:
    """Next UTC midnight."""
    d = (now or datetime.now(UTC)).astimezone(UTC)
    return datetime(d.year, d.month, d.day, tzinfo=UTC) + timedelta(days=1)


def reserve_run(repo: Repo, settings: Settings, uid: str, now: datetime | None = None) -> str:
    """Reserve one run slot; returns the UTC date key to pass to `release_run`."""
    date = utc_date(now)
    outcome = repo.reserve_run(uid, date, settings.daily_run_cap, settings.max_active_runs)
    if outcome == "daily_cap":
        raise ApiError.of(429, "daily_cap_reached", DAILY_MESSAGE)
    if outcome == "concurrent":
        raise ApiError.of(429, "daily_cap_reached", CONCURRENT_MESSAGE)
    return date


def release_run(repo: Repo, uid: str, date: str, refund: bool) -> None:
    repo.release_run(uid, date, refund)


def usage_view(
    repo: Repo, settings: Settings, uid: str, now: datetime | None = None
) -> tuple[int, int, datetime]:
    """`(runs_today, daily_cap, resets_at)` with the per-user override applied."""
    user = repo.get_user(uid)
    cap = (
        user.daily_cap
        if user is not None and user.daily_cap is not None
        else settings.daily_run_cap
    )
    return repo.get_usage(uid, utc_date(now)).runs, cap, resets_at(now)
