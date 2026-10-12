"""Keep the reference docs in step with the code. Offline; skipped without a docs directory."""

import re
from pathlib import Path

import pytest

from iaudit_backend.config import Settings
from iaudit_backend.models.audit import WarningCode

REPO = Path(__file__).resolve().parents[2]
DOCS = REPO / "docs"
SRC = REPO / "backend" / "src" / "iaudit_backend"

pytestmark = pytest.mark.skipif(not DOCS.is_dir(), reason="docs directory not present")


def test_every_setting_is_in_configuration_md():
    text = (DOCS / "reference" / "configuration.md").read_text(encoding="utf-8")
    missing = [n for n in Settings.model_fields if f"`IAUDIT_{n.upper()}`" not in text]
    assert missing == []


def test_configuration_md_names_no_unknown_setting():
    text = (DOCS / "reference" / "configuration.md").read_text(encoding="utf-8")
    named = set(re.findall(r"`IAUDIT_([A-Z0-9_]+)`", text))
    known = {n.upper() for n in Settings.model_fields} | {"CONTRACTS_DIR"}
    assert named - known == set()


def test_every_http_status_the_code_sends_is_in_backend_api_md():
    app, errors = (
        (SRC / "app.py").read_text(encoding="utf-8"),
        (SRC / "api" / "errors.py").read_text(encoding="utf-8"),
    )
    sent = set(re.findall(r"ApiError\(\s*[^()]*?,\s*(\d{3})\b", app, re.S))
    sent |= set(re.findall(r"_response\(\s*(\d{3})\b", errors))
    sent |= set(re.findall(r"status_code == (\d{3})", errors))
    sent |= {"422"}  # the framework fallback in errors.py
    assert sent >= {"400", "413", "500", "503", "504"}
    doc = (DOCS / "reference" / "backend-api.md").read_text(encoding="utf-8")
    assert [s for s in sorted(sent) if s not in doc] == []


def test_every_warning_code_is_in_warnings_md():
    text = (DOCS / "reference" / "warnings.md").read_text(encoding="utf-8")
    assert [c.value for c in WarningCode if f"`{c.value}`" not in text] == []


def test_every_adr_file_is_in_the_decisions_index():
    index = (DOCS / "decisions" / "README.md").read_text(encoding="utf-8")
    files = sorted(p.name for p in (DOCS / "decisions").glob("[0-9][0-9][0-9][0-9]-*.md"))
    assert files and [f for f in files if f"({f})" not in index] == []


_LINK = re.compile(r"\]\(([^)\s]+)\)")


def _markdown_files():
    files = [p for p in DOCS.rglob("*.md") if "agent_files" not in p.parts]
    files += [
        REPO / "README.md",
        REPO / "backend" / "README.md",
        REPO / "backend" / "eval" / "README.md",
    ]
    return [p for p in files if p.is_file()]


def test_relative_markdown_links_resolve():
    broken = []
    for f in _markdown_files():
        for target in _LINK.findall(f.read_text(encoding="utf-8")):
            if re.match(r"[a-z][a-z0-9+.-]*:", target) or target.startswith("#"):
                continue
            path = target.split("#")[0]
            if path and not (f.parent / path).exists():
                broken.append(f"{f.relative_to(REPO)} -> {target}")
    assert broken == []
