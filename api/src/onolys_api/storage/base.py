"""Blob store seam (private object storage). GCS in cloud, a local dir in dev/tests."""

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

MAX_UPLOAD_BYTES = 300 * 1024 * 1024
UPLOAD_URL_TTL_S = 15 * 60
READ_URL_TTL_S = 5 * 60


class BlobNotFoundError(Exception):
    pass


@dataclass(frozen=True)
class SignedUpload:
    url: str
    expires_at: datetime
    headers: dict[str, str]  # exactly what the client must send with the PUT
    method: str = "PUT"


class BlobStore(Protocol):
    @property
    def bucket(self) -> str: ...
    def uri(self, key: str) -> str: ...
    def put_bytes(
        self, key: str, data: bytes, content_type: str = "application/octet-stream"
    ) -> None: ...
    def get_bytes(self, key: str) -> bytes: ...
    def exists(self, key: str) -> bool: ...
    def size(self, key: str) -> int | None: ...
    def delete(self, key: str) -> bool: ...
    def list_keys(self, prefix: str) -> list[str]: ...
    def delete_prefix(self, prefix: str) -> int: ...
    def signed_upload(
        self,
        key: str,
        content_type: str,
        max_bytes: int = MAX_UPLOAD_BYTES,
        expires_in: int = UPLOAD_URL_TTL_S,
    ) -> SignedUpload: ...
    def signed_read_url(self, key: str, expires_in: int = READ_URL_TTL_S) -> str: ...
