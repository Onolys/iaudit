import time
from unittest.mock import MagicMock

import httpx
import pytest

from onolys_api.app import create_app
from onolys_api.repo.fake import FakeRepo
from onolys_api.storage.base import BlobNotFoundError
from onolys_api.storage.fake import FakeBlobStore
from onolys_api.storage.gcs import GcsBlobStore


@pytest.fixture
def store(tmp_path):
    return FakeBlobStore(tmp_path / "b", bucket="bkt", base_url="http://t")


def test_fake_put_get_exists_size_delete(store):
    store.put_bytes("u/s/a.bin", b"abc", "application/octet-stream")
    assert store.exists("u/s/a.bin") and store.size("u/s/a.bin") == 3
    assert store.get_bytes("u/s/a.bin") == b"abc"
    assert store.uri("u/s/a.bin") == "gs://bkt/u/s/a.bin"
    assert store.delete("u/s/a.bin") is True and store.delete("u/s/a.bin") is False
    with pytest.raises(BlobNotFoundError):
        store.get_bytes("u/s/a.bin")
    assert store.size("u/s/a.bin") is None


def test_fake_list_and_delete_prefix(store):
    for k in ("u/s/a", "u/s/b/c", "u/t/z", "uploads/u/s/x"):
        store.put_bytes(k, b"1")
    assert store.list_keys("u/s/") == ["u/s/a", "u/s/b/c"]
    assert store.delete_prefix("u/s/") == 2
    assert store.list_keys("") == ["u/t/z", "uploads/u/s/x"]


@pytest.mark.parametrize("key", ["../x", "a/../../x", "/abs", "a//b", ""])
def test_fake_rejects_unsafe_keys(store, key):
    with pytest.raises(ValueError):
        store.put_bytes(key, b"x")


def test_fake_signed_upload_shape(store):
    su = store.signed_upload("uploads/u/s/up1", "audio/mp4", 300 * 1024 * 1024, expires_in=900)
    assert su.method == "PUT"
    assert su.url.startswith("http://t/v1/_fake_blob/uploads/u/s/up1?")
    assert su.headers["Content-Type"] == "audio/mp4"
    assert su.headers["x-goog-content-length-range"] == f"0,{300 * 1024 * 1024}"
    assert su.expires_at.timestamp() > time.time()


@pytest.fixture
async def fake_app_client(store):
    app = create_app(repo=FakeRepo(store), blobs=store)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app, raise_app_exceptions=False), base_url="http://t"
    ) as c:
        yield c


async def test_fake_signed_urls_are_served_by_the_app(fake_app_client, store):
    su = store.signed_upload("uploads/u/s/up1", "audio/wav", 100)
    path = su.url.removeprefix("http://t")
    r = await fake_app_client.put(path, content=b"RIFFdata", headers=su.headers)
    assert r.status_code == 200
    assert store.get_bytes("uploads/u/s/up1") == b"RIFFdata"
    read_url = store.signed_read_url("uploads/u/s/up1", expires_in=60).removeprefix("http://t")
    g = await fake_app_client.get(read_url)
    assert g.status_code == 200 and g.content == b"RIFFdata"


async def test_fake_signed_upload_enforces_type_size_and_signature(fake_app_client, store):
    su = store.signed_upload("uploads/u/s/up1", "audio/wav", 4)
    path = su.url.removeprefix("http://t")
    wrong_type = await fake_app_client.put(path, content=b"abc", headers={"Content-Type": "x/y"})
    too_big = await fake_app_client.put(path, content=b"abcde", headers=su.headers)
    tampered = await fake_app_client.put(
        path.replace("up1", "up2"), content=b"abc", headers=su.headers
    )
    assert wrong_type.status_code == 403 and too_big.status_code == 403
    assert tampered.status_code == 403
    assert not store.exists("uploads/u/s/up1") and not store.exists("uploads/u/s/up2")


async def test_fake_signed_url_expired(fake_app_client, store):
    su = store.signed_upload("uploads/u/s/up1", "audio/wav", 100, expires_in=-5)
    r = await fake_app_client.put(su.url.removeprefix("http://t"), content=b"a", headers=su.headers)
    assert r.status_code == 403


async def test_fake_route_absent_for_non_fake_store():
    app = create_app(repo=FakeRepo(MagicMock()), blobs=MagicMock())
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        assert (await c.get("/v1/_fake_blob/x?exp=1&sig=a&m=GET")).status_code == 404


# ---- GCS (mocked client; no network) ----


def _gcs():
    client = MagicMock()
    bucket = client.bucket.return_value
    return GcsBlobStore(client, "onolys-audio-test"), client, bucket


def test_gcs_signed_upload_is_v4_put_with_pinned_headers():
    s, _client, bucket = _gcs()
    blob = bucket.blob.return_value
    blob.generate_signed_url.return_value = "https://storage.googleapis.com/signed"
    su = s.signed_upload("uploads/u/s/up1", "audio/mp4", 1000, expires_in=900)
    bucket.blob.assert_called_with("uploads/u/s/up1")
    kw = blob.generate_signed_url.call_args.kwargs
    assert kw["version"] == "v4" and kw["method"] == "PUT" and kw["content_type"] == "audio/mp4"
    assert kw["headers"] == {"x-goog-content-length-range": "0,1000"}
    assert kw["expiration"].total_seconds() == 900
    assert su.url == "https://storage.googleapis.com/signed"
    assert su.headers == {"Content-Type": "audio/mp4", "x-goog-content-length-range": "0,1000"}


def test_gcs_signed_read_is_v4_get():
    s, _c, bucket = _gcs()
    blob = bucket.blob.return_value
    blob.generate_signed_url.return_value = "https://signed/get"
    assert s.signed_read_url("u/s/audio/original.wav", expires_in=300) == "https://signed/get"
    kw = blob.generate_signed_url.call_args.kwargs
    assert kw["version"] == "v4" and kw["method"] == "GET"


class _FakeCreds:
    """Stands in for google.auth credentials: token only after refresh; expires on demand."""

    def __init__(self):
        self.valid = False
        self.token = None
        self.refreshes = 0

    def refresh(self, _request):
        self.refreshes += 1
        self.token = f"cp-token-{self.refreshes}"
        self.valid = True


def _iam_store(monkeypatch):
    import google.auth

    calls, creds = [], _FakeCreds()

    def fake_default(scopes=None, **_kw):
        calls.append(scopes)
        return creds, "onolys"

    monkeypatch.setattr(google.auth, "default", fake_default)
    client = MagicMock()
    s = GcsBlobStore(client, "b", signer_email="api-staging@onolys.iam.gserviceaccount.com")
    blob = client.bucket.return_value.blob.return_value
    blob.generate_signed_url.return_value = "u"
    return s, client, blob, creds, calls


def test_gcs_signing_via_iam_uses_cloud_platform_scoped_token(monkeypatch):
    s, client, blob, creds, calls = _iam_store(monkeypatch)
    client._credentials.token = "devstorage-only-token"
    s.signed_read_url("k")
    kw = blob.generate_signed_url.call_args.kwargs
    assert calls == [["https://www.googleapis.com/auth/cloud-platform"]]
    assert kw["service_account_email"] == "api-staging@onolys.iam.gserviceaccount.com"
    assert kw["access_token"] == "cp-token-1"  # not the storage client's token


def test_gcs_signing_refreshes_expired_token_only(monkeypatch):
    s, _client, blob, creds, calls = _iam_store(monkeypatch)
    s.signed_read_url("k")
    s.signed_read_url("k")
    assert creds.refreshes == 1 and len(calls) == 1  # still valid: reused
    creds.valid = False  # token expired
    s.signed_read_url("k")
    assert creds.refreshes == 2
    assert blob.generate_signed_url.call_args.kwargs["access_token"] == "cp-token-2"


def test_gcs_no_signer_email_skips_signing_credentials(monkeypatch):
    import google.auth

    monkeypatch.setattr(google.auth, "default", lambda **_k: pytest.fail("must not be called"))
    s, _c, bucket = _gcs()
    bucket.blob.return_value.generate_signed_url.return_value = "u"
    s.signed_read_url("k")
    assert "access_token" not in bucket.blob.return_value.generate_signed_url.call_args.kwargs


def test_gcs_put_get_exists_delete_list():
    from google.api_core.exceptions import NotFound

    s, client, bucket = _gcs()
    blob = bucket.blob.return_value
    s.put_bytes("k", b"abc", "application/json")
    blob.upload_from_string.assert_called_with(b"abc", content_type="application/json")
    blob.download_as_bytes.return_value = b"abc"
    assert s.get_bytes("k") == b"abc"
    blob.download_as_bytes.side_effect = NotFound("x")
    with pytest.raises(BlobNotFoundError):
        s.get_bytes("k")
    blob.exists.return_value = True
    assert s.exists("k") is True
    bucket.get_blob.return_value = None
    assert s.size("k") is None
    bucket.get_blob.return_value = MagicMock(size=7)
    assert s.size("k") == 7
    b1, b2 = MagicMock(), MagicMock()
    b1.name, b2.name = "p/a", "p/b"
    client.list_blobs.return_value = [b1, b2]
    assert s.list_keys("p/") == ["p/a", "p/b"]
    client.list_blobs.assert_called_with("onolys-audio-test", prefix="p/")
    assert s.delete_prefix("p/") == 2
    b1.delete.assert_called_once()
    assert s.uri("a/b") == "gs://onolys-audio-test/a/b"


# ---- file transfer helpers used by validate ----


def test_fake_download_upload_move(store, tmp_path):
    store.put_bytes("uploads/u/s/up", b"hello")
    dst = tmp_path / "x" / "in.bin"
    store.download_to("uploads/u/s/up", dst)
    assert dst.read_bytes() == b"hello"
    with pytest.raises(BlobNotFoundError):
        store.download_to("nope", tmp_path / "n")
    store.upload_from("u/s/audio/c.flac", dst, "audio/flac")
    assert store.get_bytes("u/s/audio/c.flac") == b"hello"
    store.move("uploads/u/s/up", "u/s/audio/original.wav")
    assert store.get_bytes("u/s/audio/original.wav") == b"hello"
    assert not store.exists("uploads/u/s/up")
    with pytest.raises(BlobNotFoundError):
        store.move("uploads/u/s/up", "u/s/other")


def test_gcs_download_upload_move(tmp_path):
    from google.api_core.exceptions import NotFound

    s, _client, bucket = _gcs()
    blob = bucket.blob.return_value
    s.download_to("k", tmp_path / "f")
    blob.download_to_filename.assert_called_with(str(tmp_path / "f"))
    blob.download_to_filename.side_effect = NotFound("x")
    with pytest.raises(BlobNotFoundError):
        s.download_to("k", tmp_path / "f")
    s.upload_from("k2", tmp_path / "f", "audio/flac")
    blob.upload_from_filename.assert_called_with(str(tmp_path / "f"), content_type="audio/flac")
    src = MagicMock()
    bucket.blob.return_value = src
    s.move("a", "b")
    bucket.copy_blob.assert_called_once_with(src, bucket, "b")
    src.delete.assert_called_once()
