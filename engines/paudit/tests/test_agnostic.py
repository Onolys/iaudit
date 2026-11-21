"""The engine must stay protocol-agnostic and model-agnostic (PRD R1/R5)."""

import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

SRC = Path(__file__).resolve().parents[1] / "src"
PROTOCOL = re.compile(r"miti|cct|reflection", re.I)
MODEL_ID = re.compile(
    r"claude|sonnet|haiku|opus|gemini|gpt-?\d|\bo[134]-|anthropic/|vertex_ai/|openai/|"
    r"gemini/|bedrock/|mistral|llama",
    re.I,
)


def _lines():
    files = [p for p in SRC.rglob("*") if p.is_file() and "__pycache__" not in p.parts]
    assert files, "no source files found: grep test would pass vacuously"
    for p in files:
        for n, line in enumerate(p.read_text(errors="ignore").splitlines(), 1):
            yield p, n, line


def test_no_protocol_strings_in_engine_src():
    hits = [f"{p}:{n}: {line.strip()}" for p, n, line in _lines() if PROTOCOL.search(line)]
    assert not hits, "\n".join(hits)


def test_no_model_ids_in_engine_src():
    hits = [f"{p}:{n}: {line.strip()}" for p, n, line in _lines() if MODEL_ID.search(line)]
    assert not hits, "\n".join(hits)


def test_patterns_do_catch_violations():
    for s in ("MITI 4.2.1", "cct", "Reflection", "claude-sonnet-4", "gemini/flash", "gpt-4o"):
        assert PROTOCOL.search(s) or MODEL_ID.search(s), s
