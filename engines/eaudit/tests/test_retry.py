"""The retry loop preserves outcomes, attempt numbers, and cancellation."""

import asyncio

import pytest

from eaudit.utils import retry


async def test_first_success_runs_once_without_budget_check():
    calls = []
    outcomes = []

    async def fn(attempt):
        calls.append(attempt)
        return "ready"

    def should_retry(outcome):
        outcomes.append(outcome)
        return False

    def can_continue():
        pytest.fail("the initial attempt must not check retry budget")

    assert await retry(fn, should_retry=should_retry, can_continue=can_continue) == "ready"
    assert calls == [1]
    assert outcomes == ["ready"]


@pytest.mark.parametrize("first", ["pending", ValueError("transient")])
async def test_retries_values_or_errors_then_returns_success(first):
    calls = []
    outcomes = []

    async def fn(attempt):
        calls.append(attempt)
        if attempt == 1:
            if isinstance(first, BaseException):
                raise first
            return first
        return "ready"

    def should_retry(outcome):
        outcomes.append(outcome)
        return outcome != "ready"

    assert await retry(fn, should_retry=should_retry) == "ready"
    assert calls == [1, 2]
    assert outcomes == [first, "ready"]


async def test_exhaustion_returns_last_value_and_consults_each_outcome():
    outcomes = []

    async def fn(attempt):
        return attempt

    def should_retry(outcome):
        outcomes.append(outcome)
        return True

    assert await retry(fn, attempts=3, should_retry=should_retry) == 3
    assert outcomes == [1, 2, 3]


async def test_exhaustion_reraises_last_error():
    errors = [ValueError("first"), RuntimeError("last")]

    async def fn(attempt):
        raise errors[attempt - 1]

    with pytest.raises(RuntimeError) as caught:
        await retry(fn, should_retry=lambda outcome: True)
    assert caught.value is errors[-1]


async def test_nonretryable_error_propagates_without_second_attempt():
    calls = []
    error = ValueError("permanent")

    async def fn(attempt):
        calls.append(attempt)
        raise error

    with pytest.raises(ValueError) as caught:
        await retry(fn, should_retry=lambda outcome: False)
    assert caught.value is error
    assert calls == [1]


@pytest.mark.parametrize("outcome", ["pending", ValueError("unavailable")])
async def test_false_can_continue_stops_after_initial_outcome(outcome):
    calls = []

    async def fn(attempt):
        calls.append(attempt)
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome

    async def sleep(delay):
        pytest.fail("no delay when retries are disallowed")

    if isinstance(outcome, BaseException):
        with pytest.raises(ValueError) as caught:
            await retry(fn, should_retry=lambda result: True, can_continue=lambda: False, sleep=sleep)
        assert caught.value is outcome
    else:
        assert await retry(fn, should_retry=lambda result: True, can_continue=lambda: False, sleep=sleep) == "pending"
    assert calls == [1]


async def test_exponential_delay_occurs_only_between_attempts():
    events = []

    async def fn(attempt):
        events.append(("attempt", attempt))
        return "pending"

    async def sleep(delay):
        events.append(("sleep", delay))

    assert await retry(fn, should_retry=lambda result: True, attempts=4, delay=0.5, backoff=2, sleep=sleep) == "pending"
    assert events == [
        ("attempt", 1), ("sleep", 0.5), ("attempt", 2), ("sleep", 1.0),
        ("attempt", 3), ("sleep", 2.0), ("attempt", 4),
    ]


async def test_default_zero_delay_uses_injected_sleep():
    delays = []

    async def fn(attempt):
        return attempt

    async def sleep(delay):
        delays.append(delay)

    assert await retry(fn, should_retry=lambda result: True, sleep=sleep) == 2
    assert delays == [0.0]


async def test_cancellation_from_operation_is_never_offered_for_retry():
    calls = []

    async def fn(attempt):
        calls.append(attempt)
        raise asyncio.CancelledError

    def should_retry(outcome):
        pytest.fail("cancellation must bypass retry decisions")

    with pytest.raises(asyncio.CancelledError):
        await retry(fn, should_retry=should_retry)
    assert calls == [1]


async def test_cancellation_during_sleep_stops_before_next_attempt():
    calls = []
    sleeping = asyncio.Event()

    async def fn(attempt):
        calls.append(attempt)
        return "pending"

    async def sleep(delay):
        sleeping.set()
        await asyncio.Future()

    task = asyncio.create_task(retry(fn, should_retry=lambda result: True, sleep=sleep))
    await sleeping.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert calls == [1]


@pytest.mark.parametrize("options", [
    {"attempts": 0}, {"attempts": -1}, {"attempts": 1.5}, {"attempts": True},
    {"delay": -1}, {"delay": float("nan")}, {"delay": float("inf")},
    {"backoff": -1}, {"backoff": float("nan")}, {"backoff": float("inf")},
])
async def test_invalid_options_fail_before_calling_operation(options):
    async def fn(attempt):
        pytest.fail("invalid retry options must fail before execution")

    with pytest.raises(ValueError):
        await retry(fn, should_retry=lambda result: True, **options)
