"""Task 10 / R9 / AC11: the live check on the real model (manual; excluded by `-m 'not live'`).

    set -a; . ~/.config/onolys/keys.env; set +a
    uv run --package onolys-evaluation pytest engines/evaluation/tests/test_live_check.py -m live -s
"""

import os

import pytest

from onolys_evaluation import check

pytestmark = [pytest.mark.live, pytest.mark.integration]


async def test_live_check_passes_on_the_fixture():
    if not os.environ.get("GEMINI_API_KEY"):
        pytest.skip("set GEMINI_API_KEY (live LLM)")
    result = await check.run_check(check.default_pack(), None)
    print(check.format_result(result))
    assert result.passed, result.problems
