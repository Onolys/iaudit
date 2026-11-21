"""The shipped pack renders into a valid code-pass prompt (no model call)."""

import pytest

from paudit.code_pass import build_requests_parts
from paudit.pack import default_protocols_dir, load_pack

pytestmark = pytest.mark.unit


def test_miti_prompt_renders_codes_and_examples():
    pack = load_pack("miti@4.2.1", default_protocols_dir())
    parts = build_requests_parts(pack, {"change_goal": "g"}, "en")
    first = parts.cache_prefixes[0]
    assert "### Example 1" in first and '"volleys"' in first
    assert "synthetic" not in first  # example markers are not sent to the model
    for item in pack.items:
        if item["kind"] == "count":
            assert f"- {item['id']} (" in first
    codes = parts.response_model.model_json_schema()
    assert "cr" in str(codes)
