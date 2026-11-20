"""Task 10 / R9 / D1 / D12: boundary tests. Engine stays protocol-agnostic, never imports the api
package, and the committed fixtures replay with zero network."""

import re
import socket
from pathlib import Path

import pytest
from _make_fixtures import build
from conftest import REPO

pytestmark = pytest.mark.unit

SRC = REPO / "engines" / "evaluation" / "src"
PROTOCOL = re.compile(r"miti|cct|reflection", re.I)
# The report field named by the PRD (R7) is the only allowed hit.
ALLOWED = ("not_official_miti_coding",)
EAUDIT_FILTER_FILES = (
    "check/synth.py", "check/checker.py", "pipeline/flow.py", "engine.py", "models/audit.py",
)


def _strip(text: str) -> str:
    for a in ALLOWED:
        text = text.replace(a, "")
    return text


def test_no_protocol_strings_in_evaluation_src():
    files = list(SRC.rglob("*.py"))
    assert files
    for p in files:
        assert not PROTOCOL.search(_strip(p.read_text(encoding="utf-8"))), p


def test_no_protocol_strings_in_eaudit_filter_code():
    base = REPO / "engines" / "eaudit" / "src" / "eaudit"
    for rel in EAUDIT_FILTER_FILES:
        text = (base / rel).read_text(encoding="utf-8")
        assert not PROTOCOL.search(text), rel


def test_evaluation_src_never_imports_api():
    pat = re.compile(r"^\s*(from|import)\s+(onolys_api|api)\b", re.M)
    for p in SRC.rglob("*.py"):
        assert not pat.search(p.read_text(encoding="utf-8")), p


def test_check_module_is_in_the_scanned_tree():
    assert (SRC / "onolys_evaluation" / "check.py").exists()


@pytest.mark.parametrize("variant", ["full", "partial", "no_rating"])
def test_fixtures_replay_with_zero_network(variant, monkeypatch):
    def deny(*a, **k):
        raise AssertionError("network access attempted")

    monkeypatch.setattr(socket.socket, "connect", deny)
    monkeypatch.setattr(socket, "getaddrinfo", deny)
    doc = build(variant)
    assert doc["schema_version"] == "0.0.1"
    assert Path(REPO / "protocols" / "miti-4.2.1").exists()
