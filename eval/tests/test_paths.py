import os
import stat
import subprocess
from pathlib import Path

from iaudit_eval import paths


def test_defaults_ignore_cwd(tmp_path, monkeypatch):
    monkeypatch.delenv("IAUDIT_CONTRACTS_DIR", raising=False)
    monkeypatch.delenv("IAUDIT_EVAL_HOME", raising=False)
    monkeypatch.chdir(tmp_path)
    root = paths.repo_root()
    assert (root / "docs" / "mission.md").is_file()
    assert paths.contracts_dir() == root / "docs" / "contracts"
    assert paths.eval_home() == root / "eval"
    assert paths.runs_dir() == root / "eval" / "runs"
    assert paths.data_dir() == root / "eval" / "data"


def test_env_overrides(tmp_path, monkeypatch):
    monkeypatch.setenv("IAUDIT_CONTRACTS_DIR", str(tmp_path / "c"))
    monkeypatch.setenv("IAUDIT_EVAL_HOME", str(tmp_path / "h"))
    assert paths.contracts_dir() == tmp_path / "c"
    assert paths.runs_dir() == tmp_path / "h" / "runs"
    assert paths.data_dir() == tmp_path / "h" / "data"


def _mode(p: Path) -> int:
    return stat.S_IMODE(os.stat(p).st_mode)


def test_private_modes(tmp_path):
    old = os.umask(0o022)
    try:
        f = paths.write_private_file(tmp_path / "runs" / "r1" / "items" / "a.json", "{}")
    finally:
        os.umask(old)
    assert _mode(f) == 0o600
    for d in (f.parent, f.parent.parent, f.parent.parent.parent):
        assert _mode(d) == 0o700
    paths.write_private_file(f, b"[]")
    assert _mode(f) == 0o600 and f.read_bytes() == b"[]"


def test_runs_and_data_are_gitignored():
    root = paths.repo_root()
    for p in ("eval/runs/x/run.json", "eval/data/ds/download.json"):
        r = subprocess.run(["git", "check-ignore", "-q", p], cwd=root)
        assert r.returncode == 0, p
