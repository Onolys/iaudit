"""Generic fetcher for adapter-declared dataset sources.

Streams each source to ``<data>/<name>/<filename>.part``, hashes while streaming,
``os.replace`` on success, then runs the adapter's optional ``post_download``. An adapter may
instead supply ``download(data_dir, progress) -> list[FileRecord]``. Status lives in an atomic
``download.json``. Never logs or returns file contents.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import tempfile
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

import httpx

from iaudit_eval import paths
from iaudit_eval.datasets.base import Dataset
from iaudit_eval.log import log_event
from iaudit_eval.store import atomic_write_json

STATUS_FILE = "download.json"
STATUSES = ("not_downloaded", "downloading", "ready", "failed")
_SAFE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,254}$")
_CHUNK = 1 << 16

Progress = Callable[[str, int, int | None], None]  # (filename, bytes_done, total or None)


class DatasetNotReady(RuntimeError):
    """A data_required dataset has no ready download."""


@dataclass(frozen=True)
class FileRecord:
    id: str
    filename: str
    sha256: str
    size_bytes: int
    fetched_at: str


def _now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _root(data_root: Path | None) -> Path:
    return Path(data_root) if data_root is not None else paths.data_dir()


def dataset_dir(dataset: Dataset, data_root: Path | None = None) -> Path:
    return _root(data_root) / dataset.meta.name


def _status_path(dataset: Dataset, data_root: Path | None) -> Path:
    return dataset_dir(dataset, data_root) / STATUS_FILE


def _write_status(dataset, data_root, status, files=(), error=None, warnings=()) -> dict:
    doc: dict = {
        "status": status,
        "files": [asdict(f) if isinstance(f, FileRecord) else dict(f) for f in files],
        "updated_at": _now(),
    }
    if error:
        doc["error"] = error
    if warnings:
        doc["warnings"] = list(warnings)
    atomic_write_json(_status_path(dataset, data_root), doc)
    return doc


def status(dataset: Dataset, *, data_root: Path | None = None) -> dict:
    """The download.json document, or a not_downloaded stub."""
    try:
        doc = json.loads(_status_path(dataset, data_root).read_text("utf-8"))
        if isinstance(doc, dict) and doc.get("status") in STATUSES:
            return doc
    except (OSError, ValueError):
        pass
    return {"status": "not_downloaded", "files": [], "updated_at": None}


def is_ready(dataset: Dataset, *, data_root: Path | None = None) -> bool:
    return status(dataset, data_root=data_root)["status"] == "ready"


def require_ready(dataset: Dataset, *, data_root: Path | None = None) -> None:
    """Refuse runs of data_required datasets unless the download is ready."""
    if dataset.meta.data_required and not is_ready(dataset, data_root=data_root):
        raise DatasetNotReady(
            f"dataset {dataset.meta.name!r} requires data; download status is "
            f"{status(dataset, data_root=data_root)['status']!r}"
        )


def _hash_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(_CHUNK):
            h.update(chunk)
    return h.hexdigest()


def _record_path(root: Path, name: str) -> Path | None:
    """Accept safe relative hook records, without traversing symlinks."""
    if not isinstance(name, str) or not name or "\\" in name:
        return None
    relative = Path(name)
    if relative.is_absolute() or any(part in {"", ".", ".."} for part in name.split("/")):
        return None
    target = root
    for part in relative.parts:
        target = target / part
        if target.is_symlink():
            return None
    if not target.resolve().is_relative_to(root.resolve()):
        return None
    return target


def hash_warnings(dataset: Dataset, *, data_root: Path | None = None) -> list[str]:
    """Warning strings for the engine to add to run warnings (hash drift, trust on first use)."""
    doc = status(dataset, data_root=data_root)
    out = [w for w in doc.get("warnings", []) if isinstance(w, str)]
    if doc["status"] != "ready":
        return out
    d = dataset_dir(dataset, data_root)
    for rec in doc.get("files", []):
        name = rec.get("filename", "")
        path = _record_path(d, name)
        if path is None or not path.is_file():
            out.append(f"downloaded file {name!r} is missing")
        elif _hash_file(path) != rec.get("sha256"):
            out.append(f"downloaded file {name!r} changed since it was recorded")
    return out


def _intact(dataset, data_root, doc) -> bool:
    if doc["status"] != "ready":
        return False
    d = dataset_dir(dataset, data_root)
    if callable(getattr(dataset.adapter, "download", None)):
        records = doc.get("files", [])
        if not records:
            return False
        by_name = {}
        for record in records:
            name = record.get("filename", "")
            path = _record_path(d, name)
            if path is None or not path.is_file() or name in by_name:
                return False
            if _hash_file(path) != record.get("sha256"):
                return False
            by_name[name] = record
        for name, expected in dataset.meta.get("expected_sha256", {}).items():
            if by_name.get(name, {}).get("sha256") != expected.lower():
                return False
        return True
    recorded = {r.get("id"): r for r in doc.get("files", [])}
    for s in dataset.meta.sources:
        r = recorded.get(s["id"])
        if r is None or r.get("filename") != s["filename"] or not (d / s["filename"]).is_file():
            return False
        if _hash_file(d / s["filename"]) != r.get("sha256"):
            return False
        if s.get("sha256") and s["sha256"].lower() != r.get("sha256"):
            return False
    return True


def _validate_source(s: dict) -> None:
    name = s.get("filename")
    if not isinstance(name, str) or not _SAFE_NAME.match(name) or ".." in name:
        raise ValueError(f"unsafe source filename for source {s.get('id')!r}")
    if not isinstance(s.get("id"), str) or not s["id"]:
        raise ValueError("source missing id")
    if not str(s.get("url", "")).startswith(("https://", "http://")):
        raise ValueError(f"source {s['id']!r}: url must be http(s)")


def _check_pins(sources, records) -> None:
    by_id = {r.id: r for r in records}
    for s in sources:
        r = by_id.get(s["id"])
        if r is None:
            continue
        if s.get("sha256") and s["sha256"].lower() != r.sha256:
            raise ValueError(f"sha256 mismatch for {s['filename']!r}: pinned hash differs")
        if s.get("size_bytes") is not None and int(s["size_bytes"]) != r.size_bytes:
            raise ValueError(f"size mismatch for {s['filename']!r}")


def _fetch(client, s, d: Path, progress) -> FileRecord:
    final = d / s["filename"]
    part = d / (s["filename"] + ".part")
    h = hashlib.sha256()
    n = 0
    try:
        with client.stream("GET", s["url"]) as resp:
            resp.raise_for_status()
            total = resp.headers.get("content-length")
            total = int(total) if total and total.isdigit() else None
            fd = os.open(part, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, paths.FILE_MODE)
            with os.fdopen(fd, "wb") as f:
                for chunk in resp.iter_bytes(_CHUNK):
                    f.write(chunk)
                    h.update(chunk)
                    n += len(chunk)
                    if progress:
                        progress(s["filename"], n, total)
                f.flush()
                os.fsync(f.fileno())
        rec = FileRecord(s["id"], s["filename"], h.hexdigest(), n, _now())
        _check_pins([s], [rec])
        os.replace(part, final)
        return rec
    finally:
        part.unlink(missing_ok=True)


def download(
    dataset: Dataset,
    *,
    progress: Progress | None = None,
    data_root: Path | None = None,
    transport: httpx.BaseTransport | None = None,
) -> dict:
    """Fetch the dataset's sources. Returns the final download.json document."""
    name = dataset.meta.name
    prior = status(dataset, data_root=data_root)
    override = getattr(dataset.adapter, "download", None)
    if _intact(dataset, data_root, prior) and dataset.meta.sources:
        log_event("download_noop", dataset=name, status="ready")
        return prior
    d = paths.ensure_private_dir(dataset_dir(dataset, data_root))
    _write_status(dataset, data_root, "downloading")
    log_event("download_start", dataset=name, status="downloading")
    stage = backup = None
    try:
        sources = [dict(s) for s in dataset.meta.sources]
        for s in sources:
            _validate_source(s)
        if callable(override):
            stage = Path(tempfile.mkdtemp(prefix=f".{name}-", dir=d.parent))
            # A custom hook can reuse pinned revisions without copying large raw sources.
            if (d / "manifest.json").is_file():
                shutil.copyfile(d / "manifest.json", stage / "manifest.json")
            records = list(override(stage, progress))
            for record in records:
                path = _record_path(stage, record.filename)
                if path is None or not path.is_file() or _hash_file(path) != record.sha256:
                    raise ValueError(f"invalid download record {record.filename!r}")
            _check_pins(sources, records)
        else:
            records = []
            with httpx.Client(
                transport=transport, follow_redirects=True, timeout=httpx.Timeout(60.0)
            ) as client:
                for s in sources:
                    records.append(_fetch(client, s, d, progress))
        old = {r.get("id"): r.get("sha256") for r in prior.get("files", [])}
        warnings = [
            f"downloaded file {r.filename!r} changed upstream since first recorded"
            for r in records
            if old.get(r.id) and old[r.id] != r.sha256
        ]
        post = getattr(dataset.adapter, "post_download", None)
        if callable(post):
            post(stage if stage is not None else d)
        if stage is not None:
            backup = stage.with_name(stage.name + "-backup")
            os.replace(d, backup)
            os.replace(stage, d)
        doc = _write_status(dataset, data_root, "ready", records, warnings=warnings)
        log_event("download_done", dataset=name, status="ready", count=len(records))
        return doc
    except Exception as exc:  # any failure is a recorded, retryable state
        if backup is not None and backup.exists():
            if d.exists():
                shutil.rmtree(d)
            os.replace(backup, d)
        err = f"{type(exc).__name__}: {str(exc)[:200]}"
        doc = _write_status(dataset, data_root, "failed", error=err)
        log_event("download_failed", dataset=name, status="failed", exc_class=type(exc).__name__)
        return doc
    finally:
        for leftover in (stage, backup):
            if leftover is not None and leftover.exists():
                shutil.rmtree(leftover, ignore_errors=True)
