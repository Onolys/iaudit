"""GCS V4 blob store. Signing uses IAM `signBlob` when `signer_email` is given (Cloud Run)."""

from datetime import UTC, datetime, timedelta
from typing import Any

from google.api_core.exceptions import NotFound

from onolys_api.storage.base import (
    MAX_UPLOAD_BYTES,
    READ_URL_TTL_S,
    UPLOAD_URL_TTL_S,
    BlobNotFoundError,
    SignedUpload,
)


class GcsBlobStore:
    def __init__(self, client: Any, bucket: str, signer_email: str | None = None) -> None:
        self._client = client
        self._bucket_name = bucket
        self._bucket = client.bucket(bucket)
        self._signer_email = signer_email

    @property
    def bucket(self) -> str:
        return self._bucket_name

    def uri(self, key: str) -> str:
        return f"gs://{self._bucket_name}/{key}"

    def put_bytes(
        self, key: str, data: bytes, content_type: str = "application/octet-stream"
    ) -> None:
        self._bucket.blob(key).upload_from_string(data, content_type=content_type)

    def get_bytes(self, key: str) -> bytes:
        try:
            return self._bucket.blob(key).download_as_bytes()
        except NotFound:
            raise BlobNotFoundError(key) from None

    def exists(self, key: str) -> bool:
        return bool(self._bucket.blob(key).exists())

    def size(self, key: str) -> int | None:
        blob = self._bucket.get_blob(key)
        return None if blob is None else blob.size

    def delete(self, key: str) -> bool:
        try:
            self._bucket.blob(key).delete()
            return True
        except NotFound:
            return False

    def list_keys(self, prefix: str) -> list[str]:
        return sorted(b.name for b in self._client.list_blobs(self._bucket_name, prefix=prefix))

    def delete_prefix(self, prefix: str) -> int:
        n = 0
        for blob in list(self._client.list_blobs(self._bucket_name, prefix=prefix)):
            try:
                blob.delete()
                n += 1
            except NotFound:
                pass
        return n

    def _signing_kwargs(self) -> dict[str, Any]:
        if not self._signer_email:
            return {}
        from google.auth.transport.requests import Request

        creds = self._client._credentials  # noqa: SLF001 (needed for IAM-based V4 signing)
        creds.refresh(Request())
        return {"service_account_email": self._signer_email, "access_token": creds.token}

    def signed_upload(
        self,
        key: str,
        content_type: str,
        max_bytes: int = MAX_UPLOAD_BYTES,
        expires_in: int = UPLOAD_URL_TTL_S,
    ) -> SignedUpload:
        range_header = {"x-goog-content-length-range": f"0,{max_bytes}"}
        url = self._bucket.blob(key).generate_signed_url(
            version="v4",
            expiration=timedelta(seconds=expires_in),
            method="PUT",
            content_type=content_type,
            headers=range_header,
            **self._signing_kwargs(),
        )
        return SignedUpload(
            url=url,
            expires_at=datetime.now(UTC) + timedelta(seconds=expires_in),
            headers={"Content-Type": content_type, **range_header},
        )

    def signed_read_url(self, key: str, expires_in: int = READ_URL_TTL_S) -> str:
        return self._bucket.blob(key).generate_signed_url(
            version="v4",
            expiration=timedelta(seconds=expires_in),
            method="GET",
            **self._signing_kwargs(),
        )
