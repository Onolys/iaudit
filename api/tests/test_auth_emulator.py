"""Auth + /v1/api-key end to end over FirestoreRepo (emulator). Skipped without the emulator."""

import os
import uuid

import httpx
import pytest

from onolys_api.app import create_app
from onolys_api.config import Settings
from onolys_api.repo.firestore import FirestoreRepo
from onolys_api.storage.fake import FakeBlobStore

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not os.environ.get("FIRESTORE_EMULATOR_HOST"),
        reason="FIRESTORE_EMULATOR_HOST not set (run under firebase emulators:exec)",
    ),
]


@pytest.fixture
async def fs_client(tmp_path):
    from google.auth.credentials import AnonymousCredentials
    from google.cloud import firestore

    blobs = FakeBlobStore(tmp_path / "blobs")
    repo = FirestoreRepo(
        firestore.Client(project="demo-onolys", credentials=AnonymousCredentials()), blobs
    )
    app = create_app(Settings(env="test", auth_mode="fake"), repo=repo, blobs=blobs)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app, raise_app_exceptions=False), base_url="http://t"
    ) as c:
        yield c, repo


async def test_key_lifecycle_against_emulator(fs_client):
    c, repo = fs_client
    uid = "u-" + uuid.uuid4().hex[:10]
    h = {"Authorization": f"Bearer test:{uid}"}

    assert (await c.get("/v1/api-key", headers=h)).json()["active"] is False
    assert repo.get_user(uid) is not None  # created on first sight

    old = (await c.post("/v1/api-key", headers=h)).json()
    new = (await c.post("/v1/api-key", headers=h)).json()
    assert repo.active_api_key(uid).id == new["key_id"]
    assert repo.get_api_key(old["key_id"]).revoked_at is not None

    # API keys authenticate but are refused on key management; revoked key is 401
    assert (await c.get("/v1/api-key", headers={"X-API-Key": new["api_key"]})).status_code == 403
    assert repo.get_api_key(new["key_id"]).last_used_at is not None
    r = await c.get("/v1/api-key", headers={"X-API-Key": old["api_key"]})
    assert r.status_code == 401 and r.json()["details"][0]["code"] == "unauthenticated"

    assert (await c.delete("/v1/api-key", headers=h)).status_code == 204
    assert repo.active_api_key(uid) is None
