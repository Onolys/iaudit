"""warm_then_fanout: the first call finishes before any other starts; results keep order."""

import asyncio

import pytest

from onolys_core.llm.warm import warm_then_fanout


async def test_no_second_call_starts_before_first_returns_and_order_kept():
    events = []

    async def first():
        events.append("first:start")
        await asyncio.sleep(0.05)
        events.append("first:end")
        return "w"

    def make(i, delay):
        async def call():
            events.append(f"rest{i}:start")
            await asyncio.sleep(delay)
            events.append(f"rest{i}:end")
            return i

        return call

    # rest[0] is slower than rest[1]: results must still follow input order
    warmed, results = await warm_then_fanout(first, [make(0, 0.03), make(1, 0.0)])

    assert warmed == "w"
    assert results == [0, 1]
    assert events.index("first:end") < events.index("rest0:start")
    assert events.index("first:end") < events.index("rest1:start")
    # the rest really run concurrently
    assert events.index("rest1:start") < events.index("rest0:end")


async def test_empty_rest_returns_first_only():
    async def first():
        return 1

    assert await warm_then_fanout(first, []) == (1, [])


async def test_first_failure_propagates_and_rest_never_start():
    started = []

    async def first():
        raise ValueError("boom")

    async def other():
        started.append(1)

    with pytest.raises(ValueError):
        await warm_then_fanout(first, [other])
    assert started == []
