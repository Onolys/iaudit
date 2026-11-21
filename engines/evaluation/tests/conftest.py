import json
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
FIXTURES = REPO / "protocols" / "miti-4.2.1" / "fixtures" / "evaluation"
SCHEMA_PATH = Path(__file__).resolve().parents[1] / "schemas" / "report.schema.json"
REPORT_NAMES = ("report_full", "report_partial", "report_no_rating")


def load(name: str):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


@pytest.fixture(scope="session")
def transcript():
    return load("transcript.json")


@pytest.fixture(scope="session", params=REPORT_NAMES)
def report_doc(request):
    return load(f"{request.param}.json")
