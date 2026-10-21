"""Filesystem locations. Resolved from the module file, never from the cwd."""

import os
from pathlib import Path

DIR_MODE = 0o700
FILE_MODE = 0o600


def repo_root() -> Path:
    # eval/src/iaudit_eval/paths.py -> repo root is parents[3]
    return Path(__file__).resolve().parents[3]


def contracts_dir() -> Path:
    env = os.environ.get("IAUDIT_CONTRACTS_DIR")
    if env:
        return Path(env)
    return repo_root() / "docs" / "contracts"


def eval_home() -> Path:
    env = os.environ.get("IAUDIT_EVAL_HOME")
    if env:
        return Path(env)
    return repo_root() / "eval"


def runs_dir() -> Path:
    return eval_home() / "runs"


def data_dir() -> Path:
    return eval_home() / "data"


def datasets_dir() -> Path:
    return eval_home() / "datasets"


def ensure_private_dir(path: Path) -> Path:
    """Create path (and missing parents below it) with mode 0700; tighten if it exists."""
    path = Path(path)
    missing = []
    p = path
    while not p.exists():
        missing.append(p)
        p = p.parent
    for d in reversed(missing):
        d.mkdir(mode=DIR_MODE)
        os.chmod(d, DIR_MODE)
    if path.is_dir():
        os.chmod(path, DIR_MODE)
    return path


def write_private_file(path: Path, data: bytes | str) -> Path:
    """Write a file with mode 0600 (created private, never briefly wider)."""
    path = Path(path)
    ensure_private_dir(path.parent)
    raw = data.encode("utf-8") if isinstance(data, str) else data
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, FILE_MODE)
    try:
        os.fchmod(fd, FILE_MODE)
        with os.fdopen(fd, "wb") as f:
            fd = -1
            f.write(raw)
    finally:
        if fd != -1:
            os.close(fd)
    return path
