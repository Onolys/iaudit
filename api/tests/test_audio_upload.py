"""POST/GET /v1/sessions/{id}/audio and /audio/complete (R2 audio, R3, D5, AC5)."""

import pytest
from audio_helpers import MAGIC, A, B, StubTools

from onolys_api.app import create_app
from onolys_api.repo.fake import FakeRepo
from onolys_api.storage.base import MAX_UPLOAD_BYTES

pytestmark = pytest.mark.unit


@pytest.fixture
def repo(blobs):
    return FakeRepo(blobs)


@pytest.fixture
def app(settings, blobs, repo):
    return create_app(settings, repo=repo, blobs=blobs, audio_tools=StubTools())


async def new_session(client, headers=A) -> str:
    r = await client.post("/v1/sessions", json={}, headers=headers)
    return r.json()["session"]["id"]


async def request_upload(client, sid, headers=A, **body):
    body.setdefault("size_bytes", 1000)
    return await client.post(f"/v1/sessions/{sid}/audio", json=body, headers=headers)


# ---- alias mapping (all four AC5 cases) ----


@pytest.mark.parametrize(
    ("body", "canonical"),
    [
        ({"content_type": "audio/x-m4a", "filename_ext": "m4a"}, "audio/mp4"),
        ({"content_type": "audio/mp4", "filename_ext": "m4a"}, "audio/mp4"),
        ({"content_type": "audio/mpeg", "filename_ext": "mp3"}, "audio/mpeg"),
        ({"content_type": "", "filename_ext": "wav"}, "audio/wav"),
        ({"content_type": "audio/x-wav"}, "audio/wav"),
        ({"content_type": "audio/webm;codecs=opus"}, "audio/webm"),
        ({"content_type": "audio/ogg"}, "audio/ogg"),
        ({"filename_ext": ".MP3"}, "audio/mpeg"),
    ],
)
async def test_alias_maps_to_canonical_required_headers(client, body, canonical):
    sid = await new_session(client)
    r = await request_upload(client, sid, **body)
    assert r.status_code == 200, r.text
    j = r.json()
    assert set(j) == {"upload_url", "upload_id", "required_headers"}
    assert j["required_headers"]["Content-Type"] == canonical
    assert j["required_headers"]["x-goog-content-length-range"] == f"0,{MAX_UPLOAD_BYTES}"


async def test_signed_url_targets_staging_prefix_and_state_is_uploading(client, repo):
    sid = await new_session(client)
    j = (await request_upload(client, sid, content_type="audio/mpeg")).json()
    assert f"uploads/alice/{sid}/{j['upload_id']}" in j["upload_url"]
    assert repo.get_session("alice", sid).state == "uploading"
    assert repo.get_status("alice", sid).state == "uploading"


@pytest.mark.parametrize(
    "body",
    [
        {"content_type": "video/mp4", "filename_ext": "mp4"},
        {"content_type": "application/pdf"},
        {"content_type": "", "filename_ext": "txt"},
        {"content_type": "", "filename_ext": ""},
    ],
)
async def test_unsupported_audio_422(client, repo, body):
    sid = await new_session(client)
    r = await request_upload(client, sid, **body)
    assert r.status_code == 422
    assert r.json()["details"][0]["code"] == "unsupported_audio"
    assert repo.get_session("alice", sid).state == "created"


async def test_audio_too_large_422(client):
    sid = await new_session(client)
    r = await request_upload(client, sid, content_type="audio/wav", size_bytes=MAX_UPLOAD_BYTES + 1)
    assert r.status_code == 422 and r.json()["details"][0]["code"] == "audio_too_large"
    ok = await request_upload(client, sid, content_type="audio/wav", size_bytes=MAX_UPLOAD_BYTES)
    assert ok.status_code == 200


async def test_size_must_be_positive(client):
    sid = await new_session(client)
    r = await request_upload(client, sid, content_type="audio/wav", size_bytes=0)
    assert r.status_code == 422 and r.json()["details"][0]["code"] == "invalid_parameters"


async def test_second_request_gets_fresh_url_and_drops_old_staged_object(client, blobs):
    sid = await new_session(client)
    first = (await request_upload(client, sid, content_type="audio/wav")).json()
    blobs.put_bytes(f"uploads/alice/{sid}/{first['upload_id']}", MAGIC["wav"])
    second = (await request_upload(client, sid, content_type="audio/wav")).json()
    assert second["upload_id"] != first["upload_id"]
    assert blobs.list_keys(f"uploads/alice/{sid}/") == []


async def test_upload_not_allowed_once_validating(client):
    sid = await new_session(client)
    await request_upload(client, sid, content_type="audio/wav")
    key = (
        await client.post(
            f"/v1/sessions/{sid}/audio",
            json={"content_type": "audio/wav", "size_bytes": 5},
            headers=A,
        )
    ).json()["upload_id"]
    app_blobs = client._transport.app.state.blobs
    app_blobs.put_bytes(f"uploads/alice/{sid}/{key}", MAGIC["wav"])
    assert (await client.post(f"/v1/sessions/{sid}/audio/complete", headers=A)).status_code == 202
    r = await request_upload(client, sid, content_type="audio/wav")
    assert r.status_code == 409 and r.json()["details"][0]["code"] == "invalid_state"


async def test_other_users_session_is_404(client):
    sid = await new_session(client)
    assert (
        await request_upload(client, sid, headers=B, content_type="audio/wav")
    ).status_code == 404
    assert (await client.post(f"/v1/sessions/{sid}/audio/complete", headers=B)).status_code == 404
    assert (await client.get(f"/v1/sessions/{sid}/audio", headers=B)).status_code == 404


async def test_requires_auth(client):
    sid = await new_session(client)
    for call in (
        client.post(f"/v1/sessions/{sid}/audio", json={"size_bytes": 1}),
        client.post(f"/v1/sessions/{sid}/audio/complete"),
        client.get(f"/v1/sessions/{sid}/audio"),
    ):
        assert (await call).status_code == 401


# ---- complete ----


async def test_complete_returns_202_enqueues_validate_and_sets_validating(client, app, repo, blobs):
    sid = await new_session(client)
    j = (await request_upload(client, sid, content_type="audio/wav")).json()
    put = await client.put(
        j["upload_url"].removeprefix("http://localhost:8000"),
        content=MAGIC["wav"], headers=j["required_headers"],
    )  # fmt: skip
    assert put.status_code == 200
    r = await client.post(f"/v1/sessions/{sid}/audio/complete", headers=A)
    assert r.status_code == 202
    assert r.json() == {"session": {"id": sid, "status": "validating"}}
    assert repo.get_status("alice", sid).state == "validating"
    assert [(p.kind, p.sid) for p in app.state.queue.pending] == [("validate", sid)]


async def test_complete_twice_is_idempotent(client, app):
    sid = await new_session(client)
    j = (await request_upload(client, sid, content_type="audio/wav")).json()
    app.state.blobs.put_bytes(f"uploads/alice/{sid}/{j['upload_id']}", MAGIC["wav"])
    for _ in range(2):
        assert (
            await client.post(f"/v1/sessions/{sid}/audio/complete", headers=A)
        ).status_code == 202
    assert len(app.state.queue.pending) == 1  # task-name dedup


async def test_complete_without_upload_request_is_409(client):
    sid = await new_session(client)
    r = await client.post(f"/v1/sessions/{sid}/audio/complete", headers=A)
    assert r.status_code == 409 and r.json()["details"][0]["code"] == "invalid_state"


async def test_complete_without_uploaded_object_is_409(client, repo):
    sid = await new_session(client)
    await request_upload(client, sid, content_type="audio/wav")
    r = await client.post(f"/v1/sessions/{sid}/audio/complete", headers=A)
    assert r.status_code == 409 and r.json()["details"][0]["code"] == "invalid_state"
    assert repo.get_session("alice", sid).state == "uploading"


# ---- GET audio ----


async def test_get_audio_before_validation_is_404(client):
    sid = await new_session(client)
    assert (await client.get(f"/v1/sessions/{sid}/audio", headers=A)).status_code == 404


async def test_get_audio_returns_signed_read_of_the_original(client, app, blobs):
    from onolys_api.repo.models import RecordingDoc

    sid = await new_session(client)
    key = f"alice/{sid}/audio/original.m4a"
    blobs.put_bytes(key, b"x")
    app.state.repo.add_recording(
        "alice", sid, "original", RecordingDoc(gcs_uri=blobs.uri(key), format="m4a")
    )
    r = await client.get(f"/v1/sessions/{sid}/audio", headers=A)
    assert r.status_code == 200
    j = r.json()
    assert key in j["url"] and "expires_at" in j
    got = await client.get(j["url"].removeprefix("http://localhost:8000"))
    assert got.status_code == 200 and got.content == b"x"
