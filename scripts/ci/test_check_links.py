"""Link checker: fails on a broken relative link, passes once the target exists."""
import importlib.util
from pathlib import Path

_spec = importlib.util.spec_from_file_location("check_links", Path(__file__).with_name("check_links.py"))
check_links = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(check_links)


def test_broken_then_fixed(tmp_path):
    (tmp_path / "a.md").write_text("see [b](b.md) and [web](https://x.y) and [h](#top)\n")
    assert check_links.broken_links(tmp_path) == ["a.md:1: b.md"]
    (tmp_path / "b.md").write_text("ok\n")
    assert check_links.broken_links(tmp_path) == []


def test_fence_and_anchor(tmp_path):
    (tmp_path / "b.md").write_text("x\n")
    (tmp_path / "a.md").write_text("[b](b.md#sec)\n```\n[no](missing.md)\n```\n")
    assert check_links.broken_links(tmp_path) == []


def test_repo_has_no_broken_links():
    assert check_links.broken_links(Path(__file__).resolve().parents[2]) == []
