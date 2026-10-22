"""Run store. Item files are the truth; run.json totals are always recomputed.

Every function takes an explicit runs root (``None`` = ``paths.runs_dir()``).
All writes are atomic: temp file in the same dir, fsync, os.replace, fsync dir.
"""

import fcntl
import json
import os
import re
import secrets
import time
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

from iaudit_eval import paths
from iaudit_eval.datasets.base import ID_RE

STORE_VERSION = 1
STORED_STATES = ("running", "finished", "aborted_cost", "aborted", "failed")
_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


class RunLockedError(RuntimeError):
    """Another writer holds the lock for this run."""


def _root(root: Path | None) -> Path:
    return Path(root) if root is not None else paths.runs_dir()


def _check_id(value: str, what: str) -> str:
    if not isinstance(value, str) or not _SAFE_ID.match(value) or ".." in value:
        raise ValueError(f"unsafe {what}")
    return value


def run_dir(root: Path | None, run_id: str) -> Path:
    return _root(root) / _check_id(run_id, "run_id")


def new_run_id(dataset: str) -> str:
    _check_id(dataset, "dataset")
    ts = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    return f"{ts}-{dataset}-{secrets.token_hex(3)}"


# ---------- atomic writes ----------

def _fsync_dir(d: Path) -> None:
    fd = os.open(d, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def atomic_write_json(path: Path, obj: object) -> None:
    path = Path(path)
    paths.ensure_private_dir(path.parent)
    tmp = path.parent / f".{path.name}.tmp"
    data = json.dumps(obj, indent=2, sort_keys=True, ensure_ascii=False).encode("utf-8")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, paths.FILE_MODE)
    try:
        os.fchmod(fd, paths.FILE_MODE)
        with os.fdopen(fd, "wb") as f:
            fd = -1
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
    finally:
        if fd != -1:
            os.close(fd)
    os.replace(tmp, path)
    _fsync_dir(path.parent)


def clean_stale_tmp(root: Path | None, run_id: str) -> int:
    d = run_dir(root, run_id)
    n = 0
    for p in list(d.glob(".*.tmp")) + list((d / "items").glob(".*.tmp")):
        p.unlink(missing_ok=True)
        n += 1
    return n


# ---------- lock ----------

_ACQUIRE_TRIES = 6
_ACQUIRE_PAUSE_S = 0.02


class RunLock:
    """Exclusive non-blocking flock on run.lock; released on exit or crash."""

    def __init__(self, root: Path | None, run_id: str):
        self.path = run_dir(root, run_id) / "run.lock"
        self._fd = -1

    def acquire(self) -> "RunLock":
        paths.ensure_private_dir(self.path.parent)
        fd = os.open(self.path, os.O_RDWR | os.O_CREAT, paths.FILE_MODE)
        try:
            os.fchmod(fd, paths.FILE_MODE)
            # A concurrent is_locked probe holds a shared lock for an instant; retry
            # briefly so a read never makes a real writer fail.
            for attempt in range(_ACQUIRE_TRIES):
                try:
                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    if attempt == _ACQUIRE_TRIES - 1:
                        raise
                    time.sleep(_ACQUIRE_PAUSE_S)
        except OSError as e:
            os.close(fd)
            raise RunLockedError("run is locked by another writer") from e
        self._fd = fd
        return self

    def release(self) -> None:
        if self._fd != -1:
            os.close(self._fd)  # closing drops the flock
            self._fd = -1

    def __enter__(self) -> "RunLock":
        return self.acquire()

    def __exit__(self, *exc) -> None:
        self.release()


def is_locked(root: Path | None, run_id: str) -> bool:
    lock = run_dir(root, run_id) / "run.lock"
    try:
        fd = os.open(lock, os.O_RDONLY)
    except FileNotFoundError:
        return False
    try:
        # Shared probe: never excludes another prober, and a writer retries past it.
        fcntl.flock(fd, fcntl.LOCK_SH | fcntl.LOCK_NB)
    except BlockingIOError:
        return True
    finally:
        os.close(fd)
    return False


# ---------- run.json ----------

def create_run(root: Path | None, meta: dict) -> str:
    """Create the run dir and run.json (state running). meta supplies the PRD fields."""
    run_id = meta.get("run_id") or new_run_id(meta["dataset"])
    d = run_dir(root, run_id)
    paths.ensure_private_dir(d / "items")
    run = {
        "tags": {}, "mapping_version": None, "backend_url": None, "finished_at": None,
        "git_commit": None, "git_dirty": None, "git_diff_sha256": None,
        "schema_version": None, "fingerprint": None, "mixed": False,
        "resumes": [], "warnings": [],
        "totals": {"ok": 0, "failed": 0, "missing": len(meta.get("item_ids", [])), "partial": 0,
                   "input_tokens": None, "output_tokens": None, "cost_usd": None},
        **meta,
        "run_id": run_id,
        "store_version": STORE_VERSION,
        "state": "running",
        "created_at": meta.get("created_at") or datetime.now(UTC).isoformat(),
    }
    atomic_write_json(d / "run.json", run)
    return run_id


def load_run(root: Path | None, run_id: str) -> dict:
    return json.loads((run_dir(root, run_id) / "run.json").read_text(encoding="utf-8"))


def update_run(root: Path | None, run_id: str, **fields) -> dict:
    if "state" in fields and fields["state"] not in STORED_STATES:
        raise ValueError("invalid stored state")
    run = load_run(root, run_id)
    run.update(fields)
    atomic_write_json(run_dir(root, run_id) / "run.json", run)
    return run


def list_runs(root: Path | None = None) -> list[dict]:
    base = _root(root)
    if not base.is_dir():
        return []
    out = []
    for d in sorted(base.iterdir(), reverse=True):
        try:
            out.append(json.loads((d / "run.json").read_text(encoding="utf-8")))
        except (OSError, ValueError):
            continue
    return out


def effective_state(root: Path | None, run_id: str) -> str:
    state = load_run(root, run_id)["state"]
    if state == "running" and not is_locked(root, run_id):
        return "interrupted"
    return state


# ---------- items ----------

def write_item(root: Path | None, run_id: str, item: dict) -> None:
    item_id = item["item_id"]
    if not isinstance(item_id, str) or not ID_RE.fullmatch(item_id):
        raise ValueError("unsafe item_id")
    atomic_write_json(run_dir(root, run_id) / "items" / f"{item_id}.json", item)


def iter_items(root: Path | None, run_id: str) -> Iterator[dict]:
    items = run_dir(root, run_id) / "items"
    if not items.is_dir():
        return
    for p in sorted(items.glob("*.json")):
        yield json.loads(p.read_text(encoding="utf-8"))


def _sum(values: list) -> int | float | None:
    vals = [v for v in values if isinstance(v, int | float) and not isinstance(v, bool)]
    return sum(vals) if vals else None


def compute_totals(root: Path | None, run_id: str) -> dict:
    run = load_run(root, run_id)
    ok = failed = partial = 0
    seen = set()
    infos = []
    for it in iter_items(root, run_id):
        seen.add(it["item_id"])
        if it.get("status") == "failed":
            failed += 1
            continue
        if it.get("response_status") == "partial":
            partial += 1
        else:
            ok += 1
        if it.get("run_info"):
            infos.append(it["run_info"])
    missing = len([i for i in run.get("item_ids", []) if i not in seen])
    return {
        "ok": ok, "failed": failed, "missing": missing, "partial": partial,
        "input_tokens": _sum([i.get("input_tokens") for i in infos]),
        "output_tokens": _sum([i.get("output_tokens") for i in infos]),
        "cost_usd": _sum([i.get("cost_usd") for i in infos]),
    }


def refresh_totals(root: Path | None, run_id: str) -> dict:
    totals = compute_totals(root, run_id)
    update_run(root, run_id, totals=totals)
    return totals


def progress(root: Path | None, run_id: str) -> dict:
    run = load_run(root, run_id)
    t = compute_totals(root, run_id)
    return {
        "run_id": run_id,
        "state": effective_state(root, run_id),
        "done": t["ok"] + t["partial"],
        "failed": t["failed"],
        "total": len(run.get("item_ids", [])),
        "cost_usd": t["cost_usd"],
    }
