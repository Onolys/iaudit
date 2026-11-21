"""D1/D12: core never imports evaluation; engine stays protocol-agnostic."""

import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

REPO = Path(__file__).resolve().parents[3]


def test_core_does_not_import_evaluation():
    for p in (REPO / "engines" / "core" / "src").rglob("*.py"):
        assert "onolys_evaluation" not in p.read_text(encoding="utf-8"), p


def test_no_protocol_strings_in_engine_src():
    # The report field `not_official_miti_coding` is named by the PRD (R7); the only allowed hit.
    pat = re.compile(r"miti|cct|reflection", re.I)
    for p in (REPO / "engines" / "evaluation" / "src").rglob("*.py"):
        text = p.read_text(encoding="utf-8").replace("not_official_miti_coding", "")
        assert not pat.search(text), p
