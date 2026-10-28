import json
from pathlib import Path

import pytest

CONTRACTS = Path(__file__).resolve().parents[2] / "docs" / "contracts"


@pytest.fixture
def example_request() -> dict:
    return json.loads((CONTRACTS / "examples" / "request.json").read_text())


@pytest.fixture
def example_response() -> dict:
    return json.loads((CONTRACTS / "examples" / "response.json").read_text())


@pytest.fixture
def make_ctx():
    """Factory for a RequestContext with a StubClient (offline)."""
    import time

    from eaudit.config import Settings
    from eaudit.llm import MetricsCollector, StubClient
    from eaudit.pipeline import RequestContext

    def factory(llm=None, deadline_in=60.0, request_id="r1", **settings):
        return RequestContext(
            settings=Settings(**settings),
            llm=llm or StubClient(),
            metrics=MetricsCollector(),
            request_id=request_id,
            deadline=time.monotonic() + deadline_in,
        )

    return factory
