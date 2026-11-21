"""Large-object rule (D11): inline in Firestore up to 500 KB, else a GCS JSON object + pointer."""

import json
from typing import Any

from onolys_api.repo.models import BlobPointer
from onolys_api.storage.base import BlobStore

MAX_INLINE_BYTES = 500 * 1024


def transcript_key(uid: str, sid: str) -> str:
    return f"{uid}/{sid}/transcript.json"


def report_key(uid: str, sid: str, report_id: str) -> str:
    return f"{uid}/{sid}/reports/{report_id}.json"


def pack(blobs: BlobStore, key: str, payload: dict[str, Any]) -> BlobPointer | None:
    """Return None when `payload` fits inline; else store it at `key` and return the pointer."""
    data = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode()
    if len(data) <= MAX_INLINE_BYTES:
        return None
    blobs.put_bytes(key, data, "application/json")
    return BlobPointer(key=key, uri=blobs.uri(key), size_bytes=len(data))


def unpack(blobs: BlobStore, pointer: BlobPointer) -> dict[str, Any]:
    return json.loads(blobs.get_bytes(pointer.key))
