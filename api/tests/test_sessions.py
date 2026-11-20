"""POST/GET /v1/sessions: create (idempotent), list, get, status doc (R2, R7, AC11)."""

import json
from datetime import UTC, datetime, timedelta

import httpx
import pytest

from onolys_api.app import create_app
from onolys_api.jobs import machine as m
from onolys_api.repo.fake import FakeRepo
from onolys_api.repo.models import IdempotencyDoc, SessionError

A = {"Authorization": "Bearer test:alice"}
B = {"Authorization": "Bearer test:bob"}
STATUS_KEYS = {
    "uid", "state", "step", "progress", "error_code", "latest_report_version", "updated_at",
    "transcript_ready", "speaker_confirmed", "rating_submitted", "has_rating",
}  # fmt: skip


@pytest.fixture
def repo(blobs):
    return FakeRepo(blobs)


@pytest.fixture
def app(settings, blobs, repo):
    return create_app(settings, repo=repo, blobs=blobs)


async def create(client, headers=A, **body):
    return await client.post("/v1/sessions", json=body, headers=headers)


async def test_create_returns_202_and_ids(client):
    r = await create(client, language="en", n_runs=2, title="Mock 1")
    assert r.status_code == 202
    body = r.json()
    assert body["session"]["status"] == "created" and len(body["session"]["id"]) >= 16
    assert set(body) == {"session"}


async def test_requires_auth(client):
    r = await client.post("/v1/sessions", json={})
    assert r.status_code == 401


async def test_status_doc_exists_before_return_written_in_the_same_batch(client, repo):
    r = await create(client)
    sid = r.json()["session"]["id"]
    st = repo.get_status("alice", sid)  # exists as soon as the call returned
    assert (st.state, st.progress, st.uid) == ("created", 0, "alice")
    assert [w[1] for w in repo.status_writes] == [sid]
    assert sorted(repo.paths(sid)) == [f"session_status/{sid}", f"sessions/{sid}"]


async def test_status_doc_schema_has_no_text(client, repo):
    sid = (await create(client, title="PHI-LOOKING TITLE", language="en")).json()["session"]["id"]
    stored = repo._docs[f"session_status/{sid}"]
    assert set(stored) == STATUS_KEYS == m.STATUS_FIELDS
    assert "PHI-LOOKING TITLE" not in json.dumps(stored, default=str)
    for k, v in stored.items():
        assert not isinstance(v, (dict, list)), k
        assert not isinstance(v, str) or k in {"uid", "state", "step", "error_code"}


async def test_session_defaults_and_stt_resolved_once_and_stored(client, repo):
    sid = (await create(client)).json()["session"]["id"]
    s = repo.get_session("alice", sid)
    assert (s.language, s.n_runs, s.preset, s.state) == ("auto", 1, "default", "created")
    assert s.stt is not None and s.stt.provider and s.stt.model and s.stt.language == "auto"
    sid2 = (await create(client, language="ja")).json()["session"]["id"]
    assert repo.get_session("alice", sid2).stt.language == "ja"  # session language wins


async def test_unknown_preset_is_422_and_nothing_is_written(client, repo):
    r = await create(client, preset="nope")
    assert r.status_code == 422 and r.json()["details"][0]["code"] == "invalid_parameters"
    assert "nope" not in r.text
    assert repo.list_sessions("alice").items == []


@pytest.mark.parametrize(
    "body",
    [{"n_runs": 0}, {"n_runs": 6}, {"language": "english please"}, {"title": "x" * 201},
     {"n_runs": "two"}],
)  # fmt: skip
async def test_invalid_bodies_are_422(client, body):
    r = await create(client, **body)
    assert r.status_code == 422


async def test_allowlisted_preset_applies_its_stt_key(tmp_path, blobs, settings):
    routes = tmp_path / "routes.yaml"
    routes.write_text(
        "cheap: &s {litellm_id: anthropic/x, api_key_env: K}\nmid: *s\nstrong: *s\n"
        "paudit_code: {alias: mid}\npaudit_globals: {alias: mid}\ntips: {alias: mid}\n"
        "presets:\n  default: {routes: {}}\n  fast: {routes: {}, stt: alt}\n"
    )
    (tmp_path / "stt_providers.yaml").write_text(
        "providers:\n  base: {provider: p1, model: m1}\n  alt: {provider: p2, model: m2}\n"
        "default: base\nby_language: {}\n"
    )
    from dataclasses import replace

    repo = FakeRepo(blobs)
    app = create_app(replace(settings, routes_file=str(routes)), repo=repo, blobs=blobs)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        sid = (await create(c, preset="fast", language="en")).json()["session"]["id"]
        sid2 = (await create(c)).json()["session"]["id"]
        assert (await create(c, preset="other")).status_code == 422
    s, s2 = repo.get_session("alice", sid), repo.get_session("alice", sid2)
    assert (s.preset, s.stt.provider, s.stt.model, s.stt.language) == ("fast", "p2", "m2", "en")
    assert (s2.preset, s2.stt.provider) == ("default", "p1")


# ---- idempotency ----


async def test_idempotent_replay_returns_original_and_creates_one_session(client, repo):
    h = {**A, "Idempotency-Key": "k-1"}
    r1 = await client.post("/v1/sessions", json={"language": "en"}, headers=h)
    r2 = await client.post("/v1/sessions", json={"language": "en"}, headers=h)
    assert r1.status_code == r2.status_code == 202
    assert r1.json() == r2.json()
    assert r2.headers["idempotent-replayed"] == "true"
    assert len(repo.list_sessions("alice").items) == 1


async def test_same_key_different_body_is_409_conflict(client, repo, schema):
    h = {**A, "Idempotency-Key": "k-2"}
    await client.post("/v1/sessions", json={"language": "en"}, headers=h)
    r = await client.post("/v1/sessions", json={"language": "fr"}, headers=h)
    assert r.status_code == 409 and r.json()["details"][0]["code"] == "conflict"
    assert len(repo.list_sessions("alice").items) == 1


async def test_idempotency_keys_are_per_user(client, repo):
    key = {"Idempotency-Key": "shared"}
    a = await client.post("/v1/sessions", json={}, headers={**A, **key})
    b = await client.post("/v1/sessions", json={}, headers={**B, **key})
    assert a.json() != b.json() and b.status_code == 202


async def test_expired_key_creates_a_new_session(client, repo):
    h = {**A, "Idempotency-Key": "k-3"}
    r1 = await client.post("/v1/sessions", json={}, headers=h)
    doc = repo.get_idempotency("alice", "k-3")
    repo.delete_idempotency("alice", "k-3")
    repo.put_idempotency(
        "alice", "k-3", IdempotencyDoc(body_hash=doc.body_hash, response=doc.response,
                                       created_at=datetime.now(UTC) - timedelta(hours=25))
    )  # fmt: skip
    r2 = await client.post("/v1/sessions", json={}, headers=h)
    assert r2.status_code == 202 and r2.json() != r1.json()
    assert "idempotent-replayed" not in r2.headers


async def test_no_key_no_dedup(client, repo):
    await create(client)
    await create(client)
    assert len(repo.list_sessions("alice").items) == 2


async def test_lost_idempotency_race_returns_winner_and_leaves_one_session(client, repo):
    real_put = repo.put_idempotency

    def racing_put(uid, key, doc):  # another request stored its answer first
        real_put(
            uid,
            key,
            IdempotencyDoc(
                body_hash=doc.body_hash, response={"session": {"id": "winner", "status": "created"}}
            ),
        )
        return real_put(uid, key, doc)  # False now

    repo.put_idempotency = racing_put
    r = await client.post("/v1/sessions", json={}, headers={**A, "Idempotency-Key": "k-4"})
    assert r.status_code == 202 and r.json()["session"]["id"] == "winner"
    assert repo.list_sessions("alice").items == []  # our orphan was removed


async def test_overlong_key_is_422(client):
    r = await client.post("/v1/sessions", json={}, headers={**A, "Idempotency-Key": "k" * 201})
    assert r.status_code == 422


# ---- list ----


async def test_list_newest_first_with_pagination_and_isolation(client, repo):
    ids = []
    for i in range(5):
        ids.append((await create(client, title=f"t{i}")).json()["session"]["id"])
    await create(client, headers=B, title="bob's")
    r = await client.get("/v1/sessions?limit=2", headers=A)
    p1 = r.json()
    assert [i["id"] for i in p1["items"]] == ids[::-1][:2] and p1["next_cursor"]
    p2 = (await client.get(f"/v1/sessions?limit=2&cursor={p1['next_cursor']}", headers=A)).json()
    p3 = (await client.get(f"/v1/sessions?limit=2&cursor={p2['next_cursor']}", headers=A)).json()
    got = [i["id"] for p in (p1, p2, p3) for i in p["items"]]
    assert got == ids[::-1] and p3["next_cursor"] is None
    item = p1["items"][0]
    assert set(item) == {
        "id",
        "title",
        "status",
        "created_at",
        "latest_report_version",
        "error_code",
    }
    assert len((await client.get("/v1/sessions", headers=B)).json()["items"]) == 1


@pytest.mark.parametrize("q", ["limit=0", "limit=51", "limit=x", "cursor=%25%25%25"])
async def test_list_bad_params_are_422(client, q):
    await create(client)
    assert (await client.get(f"/v1/sessions?{q}", headers=A)).status_code == 422


async def test_list_cursor_of_another_users_session_is_422(client):
    sid = (await create(client, headers=B)).json()["session"]["id"]
    import base64

    cur = base64.urlsafe_b64encode(sid.encode()).decode().rstrip("=")
    assert (await client.get(f"/v1/sessions?cursor={cur}", headers=A)).status_code == 422


async def test_list_hides_deleting_sessions(client, repo):
    keep = (await create(client)).json()["session"]["id"]
    gone = (await create(client)).json()["session"]["id"]
    m.advance(repo, "alice", gone, to="deleting")
    assert [i["id"] for i in (await client.get("/v1/sessions", headers=A)).json()["items"]] == [
        keep
    ]
    assert (await client.get(f"/v1/sessions/{gone}", headers=A)).status_code == 404


# ---- get ----


async def test_get_session_snapshot(client, repo):
    sid = (await create(client, title="T", n_runs=3)).json()["session"]["id"]
    for to in ("uploading", "validating", "transcribing", "awaiting_input"):
        m.advance(repo, "alice", sid, to=to)
    m.advance(repo, "alice", sid, flags={"transcript_ready": True})
    r = await client.get(f"/v1/sessions/{sid}", headers=A)
    d = r.json()
    assert r.status_code == 200
    assert (d["status"], d["progress"], d["n_runs"], d["title"]) == ("awaiting_input", 40, 3, "T")
    assert d["flags"] == {"transcript_ready": True, "speaker_confirmed": False,
                          "rating_submitted": False, "has_rating": False}  # fmt: skip
    assert d["error"] is None and d["warnings"] == [] and d["latest_report_version"] is None
    assert d["links"]["self"] == f"/v1/sessions/{sid}" and "transcript" in d["links"]


async def test_get_failed_session_reports_error_code_only(client, repo):
    sid = (await create(client)).json()["session"]["id"]
    for to in ("uploading", "validating"):
        m.advance(repo, "alice", sid, to=to)
    m.advance(
        repo,
        "alice",
        sid,
        to="failed",
        error=SessionError(code="audio_unreadable", step="validate"),
    )
    d = (await client.get(f"/v1/sessions/{sid}", headers=A)).json()
    assert d["status"] == "failed" and d["error"] == {"code": "audio_unreadable"}


async def test_get_foreign_or_missing_is_404(client):
    sid = (await create(client)).json()["session"]["id"]
    r1 = await client.get(f"/v1/sessions/{sid}", headers=B)
    r2 = await client.get("/v1/sessions/nope", headers=B)
    assert r1.status_code == r2.status_code == 404 and r1.json()["message"] == r2.json()["message"]


async def test_errors_validate_against_public_schema(client, schema):
    import jsonschema

    for r in (
        await create(client, preset="nope"),
        await client.get("/v1/sessions/nope", headers=A),
    ):
        jsonschema.validate(r.json(), schema)
