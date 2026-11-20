"""Key guard: PR-triggered workflows must not reference LLM/STT secrets."""
import importlib.util
from pathlib import Path

_here = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location(
    "guard", _here / "check_no_llm_keys_in_pr_workflows.py"
)
guard = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(guard)
FIX = _here / "key_guard_fixtures"


def test_repo_passes():
    assert guard.violations(_here.parents[1]) == []


def test_planted_references_fail():
    found = guard.violations(FIX / "bad")
    files = {v.split(":")[0] for v in found}
    assert files == {
        ".github/workflows/planted.yml",
        ".github/workflows/planted-stt.yml",
    }
    assert any("ANTHROPIC_API_KEY" in v for v in found)
    assert any("DEEPGRAM_TOKEN" in v for v in found)


def test_non_pr_workflow_and_comments_ignored():
    assert guard.violations(FIX / "ok") == []


def test_main_exit_codes(capsys):
    assert guard.main(["x", str(FIX / "ok")]) == 0
    assert guard.main(["x", str(FIX / "bad")]) == 1
    assert "ANTHROPIC_API_KEY" in capsys.readouterr().out
