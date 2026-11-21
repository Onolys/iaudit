"""Local-directory blob store with fake signed URLs served by the app (dev and tests only)."""

import hashlib
import hmac
import os
import shutil
import tempfile
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import quote, urlencode

from onolys_api.storage.base import (
    MAX_UPLOAD_BYTES,
    READ_URL_TTL_S,
    UPLOAD_URL_TTL_S,
    BlobNotFoundError,
    SignedUpload,
)

FAKE_ROUTE = "/v1/_fake_blob"


class FakeBlobStore:
    def __init__(
        self,
        root: Path | None = None,
        bucket: str = "fake-bucket",
        base_url: str = "http://localhost:8000",
    ) -> None:
        self._root = Path(root) if root else None
        self._bucket = bucket
        self._base_url = base_url.rstrip("/")
        self._secret = os.urandom(32)

    @property
    def bucket(self) -> str:
        return self._bucket

    @property
    def root(self) -> Path:
        if self._root is None:
            self._root = Path(tempfile.mkdtemp(prefix="onolys-fake-blobs-"))
        self._root.mkdir(parents=True, exist_ok=True)
        return self._root

    def uri(self, key: str) -> str:
        return f"gs://{self._bucket}/{key}"

    def _path(self, key: str) -> Path:
        parts = key.split("/")
        if not key or key.startswith("/") or any(p in ("", ".", "..") for p in parts):
            raise ValueError("unsafe blob key")
        return self.root.joinpath(*parts)

    def put_bytes(
        self, key: str, data: bytes, content_type: str = "application/octet-stream"
    ) -> None:
        p = self._path(key)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)

    def get_bytes(self, key: str) -> bytes:
        p = self._path(key)
        if not p.is_file():
            raise BlobNotFoundError(key)
        return p.read_bytes()

    def download_to(self, key: str, dst: Path) -> None:
        p = self._path(key)
        if not p.is_file():
            raise BlobNotFoundError(key)
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(p, dst)

    def upload_from(self, key: str, src: Path, content_type: str) -> None:
        p = self._path(key)
        p.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, p)

    def move(self, src_key: str, dst_key: str) -> None:
        src, dst = self._path(src_key), self._path(dst_key)
        if not src.is_file():
            raise BlobNotFoundError(src_key)
        dst.parent.mkdir(parents=True, exist_ok=True)
        os.replace(src, dst)

    def exists(self, key: str) -> bool:
        return self._path(key).is_file()

    def size(self, key: str) -> int | None:
        p = self._path(key)
        return p.stat().st_size if p.is_file() else None

    def delete(self, key: str) -> bool:
        p = self._path(key)
        if not p.is_file():
            return False
        p.unlink()
        return True

    def list_keys(self, prefix: str) -> list[str]:
        root = self.root
        keys = (p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file())
        return sorted(k for k in keys if k.startswith(prefix))

    def delete_prefix(self, prefix: str) -> int:
        keys = self.list_keys(prefix)
        for k in keys:
            self.delete(k)
        return len(keys)

    # ---- fake signing ----

    def _sig(self, method: str, key: str, exp: int, ct: str, max_bytes: int) -> str:
        msg = f"{method}\n{key}\n{exp}\n{ct}\n{max_bytes}".encode()
        return hmac.new(self._secret, msg, hashlib.sha256).hexdigest()

    def verify(self, method: str, key: str, exp: int, ct: str, max_bytes: int, sig: str) -> bool:
        ok = hmac.compare_digest(self._sig(method, key, exp, ct, max_bytes), sig)
        return ok and exp >= time.time()

    def _url(self, method: str, key: str, expires_in: int, ct: str, max_bytes: int) -> str:
        exp = int(time.time()) + expires_in
        q = urlencode(
            {
                "m": method,
                "exp": exp,
                "ct": ct,
                "max": max_bytes,
                "sig": self._sig(method, key, exp, ct, max_bytes),
            }
        )
        return f"{self._base_url}{FAKE_ROUTE}/{quote(key)}?{q}"

    def signed_upload(
        self,
        key: str,
        content_type: str,
        max_bytes: int = MAX_UPLOAD_BYTES,
        expires_in: int = UPLOAD_URL_TTL_S,
    ) -> SignedUpload:
        self._path(key)  # validates the key
        return SignedUpload(
            url=self._url("PUT", key, expires_in, content_type, max_bytes),
            expires_at=datetime.now(UTC) + timedelta(seconds=expires_in),
            headers={
                "Content-Type": content_type,
                "x-goog-content-length-range": f"0,{max_bytes}",
            },
        )

    def signed_read_url(self, key: str, expires_in: int = READ_URL_TTL_S) -> str:
        self._path(key)
        return self._url("GET", key, expires_in, "", 0)
