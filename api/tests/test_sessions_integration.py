"""Dashboard listing over a real repo: in-flight, failed and done sessions (AC2, AC11).

Runs on FakeRepo always and on the Firestore emulator when FIRESTORE_EMULATOR_HOST is set.
"""

import os
import uuid

import httpx
import pytest

from onolys_api.app import create_app
from onolys_api.config import Settings
from onolys_api.jobs import machine as m
from onolys_api.repo.fake import FakeRepo
from onolys_api.repo.models import SessionError
from onolys_api.storage.fake import FakeBlobStore

pytestmark = pytest.mark.integration
HAS_EMULATOR = bool(os.environ.get("FIRESTORE_EMULATOR_HOST"))


@pytest.fixture(params=["fake", "firestore"])
def repo(request, tmp_path):
    blobs = FakeBlobStore(tmp_path / "blobs", bucket="test-bucket")
    if request.param == "fake":
        return FakeRepo(blobs)
    if not HAS_EMULATOR:
        pytest.skip("FIRESTORE_EMULATOR_HOST not set")
    from google.auth.credentials import AnonymousCredentials
    from google.cloud import firestore

    from onolys_api.repo.firestore import FirestoreRepo

    return FirestoreRepo(
        firestore.Client(project="demo-onolys", credentials=AnonymousCredentials()), blobs
    )


async def test_list_shows_inflight_failed_and_done(repo, tmp_path):
    uid = f"u{uuid.uuid4().hex[:10]}"
    h = {"Authorization": f"Bearer test:{uid}"}
    app = create_app(Settings(env="test", auth_mode="fake"), repo=repo, blobs=repo._blobs)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        ids = {}
        for name in ("inflight", "failed", "done"):
            r = await c.post("/v1/sessions", json={"title": name}, headers=h)
            assert r.status_code == 202
            ids[name] = r.json()["session"]["id"]
        for name in ("inflight", "failed", "done"):
            for to in ("uploading", "validating", "transcribing"):
                m.advance(repo, uid, ids[name], to=to)
        m.advance(
            repo,
            uid,
            ids["failed"],
            to="failed",
            error=SessionError(code="no_speech", step="transcribe"),
        )
        for to in ("awaiting_input", "running"):
            m.advance(repo, uid, ids["done"], to=to)
        m.advance(repo, uid, ids["done"], to="report_ready", latest_report_version=2)

        # status docs agree with what the list says
        assert repo.get_status(uid, ids["done"]).progress == 100
        assert repo.get_status(uid, ids["failed"]).error_code == "no_speech"

        items = (await c.get("/v1/sessions", headers=h)).json()["items"]
        by_id = {i["id"]: i for i in items}
        assert [i["id"] for i in items] == [ids["done"], ids["failed"], ids["inflight"]]
        assert by_id[ids["inflight"]]["status"] == "transcribing"
        assert (by_id[ids["failed"]]["status"], by_id[ids["failed"]]["error_code"]) == (
            "failed",
            "no_speech",
        )
        assert (by_id[ids["done"]]["status"], by_id[ids["done"]]["latest_report_version"]) == (
            "report_ready",
            2,
        )

        p1 = (await c.get("/v1/sessions?limit=2", headers=h)).json()
        p2 = (await c.get(f"/v1/sessions?limit=2&cursor={p1['next_cursor']}", headers=h)).json()
        assert len(p1["items"]) == 2 and len(p2["items"]) == 1 and p2["next_cursor"] is None

        other = {"Authorization": "Bearer test:someone-else"}
        assert (await c.get("/v1/sessions", headers=other)).json()["items"] == []
