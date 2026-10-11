import time

import pytest

from iaudit_backend.config import Settings
from iaudit_backend.llm import MetricsCollector, StubClient
from iaudit_backend.pipeline import MIN_CALL_S, RequestContext


def ctx(deadline_in, **s):
    return RequestContext(
        settings=Settings(**s), llm=StubClient(), metrics=MetricsCollector(),
        request_id="r", deadline=time.monotonic() + deadline_in,
    )  # fmt: skip


def test_defaults_match_the_prd():
    s = Settings()
    assert (s.assemble_reserve_s, s.min_call_s, s.cancel_grace_s) == (3, 4, 1)
    assert (s.prep_call_timeout_s, s.atomize_call_timeout_s) == (10, 25)
    assert (s.link_call_timeout_s, s.check_call_timeout_s) == (20, 20)
    assert (s.prep_soft_timeout_s, s.pipeline_max_claims) == (10, 80)
    assert MIN_CALL_S == s.min_call_s


@pytest.mark.parametrize("stage,cap", [("prep", 10), ("atomize", 25), ("link", 20), ("check", 20)])
def test_stage_caps_bound_the_call_timeout(stage, cap):
    assert ctx(100).call_timeout(stage) == cap


def test_llm_timeout_is_the_ceiling_and_remaining_the_floor():
    assert ctx(100, llm_timeout_s=12).call_timeout("atomize") == 12
    assert 4 < ctx(6).call_timeout("link") <= 6


def test_no_call_starts_below_min_call_s():
    assert ctx(3.9).call_timeout("link") is None
    assert ctx(3.9, min_call_s=2).call_timeout("link") is not None
