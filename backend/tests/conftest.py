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
