"""Rating card (R2, D15, AC11, AC14): drafts, final revisions, limits, states, no GCS objects.

Runs on FakeRepo always and on the Firestore emulator when FIRESTORE_EMULATOR_HOST is set.
"""

import os
import uuid

import httpx
import pytest

from onolys_api import rating as rating_mod
from onolys_api.app import create_app
from onolys_api.config import Settings
from onolys_api.rating import validate_rating
from onolys_api.repo.fake import FakeRepo
from onolys_api.routes import rating as rating_routes

pytestmark = pytest.mark.unit
HAS_EMULATOR = bool(os.environ.get("FIRESTORE_EMULATOR_HOST"))


@pytest.fixture(params=["fake", "firestore"])
def repo(request, tmp_path):
    from onolys_api.storage.fake import FakeBlobStore

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


@pytest.fixture
def hook_calls(monkeypatch):
    calls = []
    monkeypatch.setattr(rating_routes, "maybe_start_first_run", lambda *a: calls.append(a))
    return calls


@pytest.fixture
async def env(repo, hook_calls):
    uid = f"u{uuid.uuid4().hex[:10]}"
    h = {"Authorization": f"Bearer test:{uid}"}
    app = create_app(Settings(env="test", auth_mode="fake"), repo=repo, blobs=repo._blobs)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        sid = (await c.post("/v1/sessions", json={}, headers=h)).json()["session"]["id"]
        yield c, h, repo, uid, sid


def card(**kw):
    base = {
        "change_goal": "cut back on drinking",
        "coded_span": {"from_s": 0, "to_s": 600},
        "globals": {"cct": {"score": 4, "reason": "good"}},
        "counts": {"gi": {"count": 2, "note": "n"}},
        "notes": "extra",
    }
    return {**base, **kw}


async def put(c, h, sid, body):
    return await c.put(f"/v1/sessions/{sid}/rating", json=body, headers=h)


async def test_draft_stored_never_submits_or_starts_run(env, hook_calls):
    c, h, repo, uid, sid = env
    r = await put(c, h, sid, {"final": False, "card": {"notes": "wip", "change_goal": ""}})
    assert r.status_code == 202
    s = repo.get_session(uid, sid)
    assert (s.rating_submitted, s.has_rating, s.change_goal, s.first_run_id) == (
        False, False, None, None,
    )  # fmt: skip
    assert repo.latest_rating(uid, sid) is None and repo.list_runs(uid, sid) == []
    assert repo.get_status(uid, sid).rating_submitted is False
    assert hook_calls == []
    g = (await c.get(f"/v1/sessions/{sid}/rating", headers=h)).json()
    assert g["draft"]["card"]["notes"] == "wip" and g["final"] is None


async def test_draft_overwritten_single_doc(env):
    c, h, repo, uid, sid = env
    await put(c, h, sid, {"final": False, "card": {"notes": "one"}})
    await put(c, h, sid, {"final": False, "card": {"notes": "two"}})
    g = (await c.get(f"/v1/sessions/{sid}/rating", headers=h)).json()
    assert g["draft"]["card"] == {"notes": "two"}


async def test_draft_checks_limits_only(env):
    c, h, repo, uid, sid = env
    # incomplete / wrong-shaped values are accepted in a draft
    r = await put(c, h, sid, {"final": False, "card": {"globals": {"cct": {"score": 9}}}})
    assert r.status_code == 202
    for bad in (
        {"notes": "x" * 3001},
        {"globals": {"cct": {"reason": "x" * 1001}}},
        {"globals": {"cct": {"example": {"text": "x" * 1001}}}},
        {"counts": {"gi": {"note": "x" * 1001}}},
    ):
        r = await put(c, h, sid, {"final": False, "card": bad})
        assert r.status_code == 422 and r.json()["details"][0]["code"] == "rating_invalid", bad


async def test_draft_size_cap(env):
    c, h, repo, uid, sid = env
    r = await put(c, h, sid, {"final": False, "card": {"junk": "x" * 300_000}})
    assert r.status_code == 422 and r.json()["details"][0]["code"] == "rating_invalid"


async def test_limits_at_boundary_ok(env):
    c, h, *_, sid = env
    full = card(
        notes="n" * 3000,
        globals={"cct": {"score": 5, "reason": "r" * 1000, "example": {"at_s": 3, "text": "e" * 1000}}},
        counts={"gi": {"count": 0, "note": "z" * 1000}},
    )  # fmt: skip
    assert (await put(c, h, sid, {"final": True, "card": full})).status_code == 202


@pytest.mark.parametrize(
    "bad",
    [
        {"notes": "x" * 3001},
        {"globals": {"cct": {"score": 4, "reason": "x" * 1001}}},
        {"globals": {"cct": {"score": 4, "example": {"at_s": 1, "text": "x" * 1001}}}},
        {"counts": {"gi": {"count": 1, "note": "x" * 1001}}},
        {"globals": {"cct": {"score": 6}}},
        {"globals": {"nope": {"score": 3}}},
        {"counts": {"gi": {"count": -1}}},
        {"coded_span": {"from_s": 10, "to_s": 5}},
        {"change_goal": "  "},
    ],
)
async def test_final_invalid_422_nothing_written(env, bad, hook_calls):
    c, h, repo, uid, sid = env
    r = await put(c, h, sid, {"final": True, "card": card(**bad)})
    assert r.status_code == 422
    body = r.json()
    assert body["details"][0]["code"] == "rating_invalid"
    assert "x" * 50 not in r.text
    assert repo.latest_rating(uid, sid) is None
    assert repo.get_session(uid, sid).rating_submitted is False and hook_calls == []


async def test_final_requires_change_goal(env):
    c, h, *_, sid = env
    c0 = card()
    del c0["change_goal"]
    r = await put(c, h, sid, {"final": True, "card": c0})
    assert r.status_code == 422 and r.json()["details"][0]["code"] == "rating_invalid"


async def test_final_creates_revision_and_updates_session(env, hook_calls):
    c, h, repo, uid, sid = env
    r = await put(c, h, sid, {"final": True, "card": card()})
    assert r.status_code == 202
    rid = r.json()["rating_id"]
    doc = repo.get_rating(uid, sid, rid)
    assert doc.card["change_goal"] == "cut back on drinking" and doc.no_rating is False
    s = repo.get_session(uid, sid)
    assert s.rating_submitted and s.has_rating
    assert s.change_goal == "cut back on drinking" and s.coded_span.to_s == 600
    st = repo.get_status(uid, sid)
    assert st.rating_submitted and st.has_rating
    assert len(hook_calls) == 1 and hook_calls[0][2:] == (uid, sid)


async def test_each_final_is_new_revision_latest_wins(env):
    c, h, repo, uid, sid = env
    r1 = (await put(c, h, sid, {"final": True, "card": card(change_goal="one")})).json()
    r2 = (await put(c, h, sid, {"final": True, "card": card(change_goal="two")})).json()
    assert r1["rating_id"] != r2["rating_id"]
    assert repo.get_rating(uid, sid, r1["rating_id"]).card["change_goal"] == "one"
    assert repo.latest_rating(uid, sid).id == r2["rating_id"]
    assert repo.get_session(uid, sid).change_goal == "two"
    g = (await c.get(f"/v1/sessions/{sid}/rating", headers=h)).json()
    assert g["final"]["rating_id"] == r2["rating_id"] and g["final"]["card"]["change_goal"] == "two"
    assert g.get("draft") is None


async def test_get_empty(env):
    c, h, *_, sid = env
    g = await c.get(f"/v1/sessions/{sid}/rating", headers=h)
    assert g.status_code == 200 and g.json().get("final") is None and g.json().get("draft") is None


async def test_get_draft_only_when_newer_than_final(env):
    c, h, repo, uid, sid = env
    await put(c, h, sid, {"final": False, "card": {"notes": "old draft"}})
    await put(c, h, sid, {"final": True, "card": card()})
    g = (await c.get(f"/v1/sessions/{sid}/rating", headers=h)).json()
    assert g["final"] is not None and g.get("draft") is None  # final is newer
    await put(c, h, sid, {"final": False, "card": {"notes": "newer draft"}})
    g = (await c.get(f"/v1/sessions/{sid}/rating", headers=h)).json()
    assert g["final"] is not None and g["draft"]["card"]["notes"] == "newer draft"
    assert g["draft"]["updated_at"]


async def test_draft_after_final_does_not_change_flags(env):
    c, h, repo, uid, sid = env
    await put(c, h, sid, {"final": True, "card": card()})
    await put(c, h, sid, {"final": False, "card": {"notes": "later"}})
    s = repo.get_session(uid, sid)
    assert s.rating_submitted and s.has_rating and s.change_goal == "cut back on drinking"


async def test_no_rating_flag(env):
    c, h, repo, uid, sid = env
    r = await put(c, h, sid, {"final": True, "no_rating": True, "card": {"change_goal": "g"}})
    assert r.status_code == 202
    doc = repo.get_rating(uid, sid, r.json()["rating_id"])
    assert doc.no_rating is True and doc.has_rating is False
    s = repo.get_session(uid, sid)
    assert s.rating_submitted is True and s.has_rating is False and s.change_goal == "g"
    st = repo.get_status(uid, sid)
    assert st.rating_submitted is True and st.has_rating is False
    g = (await c.get(f"/v1/sessions/{sid}/rating", headers=h)).json()
    assert g["final"]["no_rating"] is True


async def test_empty_final_card_detected_as_no_rating(env):
    c, h, repo, uid, sid = env
    empty = {
        "change_goal": "g",
        "globals": {"cct": {"score": None, "reason": ""}},
        "counts": {"gi": {"count": None}},
        "notes": "  ",
    }
    r = await put(c, h, sid, {"final": True, "card": empty})
    assert r.status_code == 202
    assert repo.get_rating(uid, sid, r.json()["rating_id"]).no_rating is True
    s = repo.get_session(uid, sid)
    assert s.rating_submitted is True and s.has_rating is False
    # a later rated revision flips has_rating on
    await put(c, h, sid, {"final": True, "card": card()})
    assert repo.get_session(uid, sid).has_rating is True


async def test_notes_alone_count_as_rating(env):
    c, h, repo, uid, sid = env
    await put(c, h, sid, {"final": True, "card": {"change_goal": "g", "notes": "some"}})
    assert repo.get_session(uid, sid).has_rating is True


@pytest.mark.parametrize(
    "state", ["created", "uploading", "validating", "transcribing", "awaiting_input", "running",
              "report_ready", "failed"],
)  # fmt: skip
async def test_allowed_in_every_state_but_deleting(env, state):
    c, h, repo, uid, sid = env
    repo.update_session(uid, sid, {"state": state}, status={"state": state})
    for final in (False, True):
        body = {"final": final, "card": card()}
        assert (await put(c, h, sid, body)).status_code == 202
    assert (await c.get(f"/v1/sessions/{sid}/rating", headers=h)).status_code == 200
    assert repo.get_session(uid, sid).state == state  # the PUT never moves the state


async def test_rejected_in_deleting(env):
    c, h, repo, uid, sid = env
    repo.update_session(uid, sid, {"state": "deleting"}, status={"state": "deleting"})
    for final in (False, True):
        r = await put(c, h, sid, {"final": final, "card": card()})
        assert r.status_code == 404
    assert (await c.get(f"/v1/sessions/{sid}/rating", headers=h)).status_code == 404
    assert repo.latest_rating(uid, sid) is None and repo.get_rating_draft(uid, sid) is None


async def test_other_user_gets_404(env):
    c, h, repo, uid, sid = env
    other = {"Authorization": "Bearer test:mallory"}
    assert (await put(c, other, sid, {"final": True, "card": card()})).status_code == 404
    assert (await c.get(f"/v1/sessions/{sid}/rating", headers=other)).status_code == 404
    assert (await c.get(f"/v1/sessions/{sid}/rating")).status_code == 401


async def test_no_object_written_to_blob_store(env):
    c, h, repo, uid, sid = env
    await put(c, h, sid, {"final": False, "card": {"notes": "d"}})
    await put(c, h, sid, {"final": True, "card": card()})
    await c.get(f"/v1/sessions/{sid}/rating", headers=h)
    assert repo._blobs.list_keys("") == []


async def test_openapi_has_rating_and_no_upload_or_parse():
    app = create_app(Settings(env="test", auth_mode="fake"))
    spec = app.openapi()
    p = spec["paths"]["/v1/sessions/{id}/rating"]
    assert set(p) == {"put", "get"} and p["put"]["operationId"] == "putRating"
    assert "202" in p["put"]["responses"]
    for path in spec["paths"]:
        low = path.lower()
        assert "parse" not in low and "upload" not in low, path
    assert not any("rating" in path and "audio" in path for path in spec["paths"])


# ---- validate_rating seam (stand-in until SP03 lands) ----


def codes(obj, final):
    return {(i.path, i.code) for i in validate_rating(obj, final=final)}


def test_validate_draft_vs_final_change_goal():
    c = card(change_goal="")
    assert validate_rating(c, final=False) == []
    assert ("change_goal", "required") in codes(c, True)
    assert validate_rating(card(), final=True) == []


def test_validate_issue_paths_carry_no_text():
    issues = validate_rating(card(notes="SECRET" * 600), final=True)
    assert issues and all("SECRET" not in i.path + i.code for i in issues)


def test_validate_shape_rules():
    assert ("globals.cct.score", "invalid") in codes({"globals": {"cct": {"score": 0}}}, False)
    assert ("globals.cct.score", "invalid") in codes({"globals": {"cct": {"score": True}}}, False)
    assert validate_rating({"globals": {"cct": {"score": None}}, "counts": {}}, final=False) == []
    assert ("coded_span", "order") in codes({"coded_span": {"from_s": 5, "to_s": 1}}, False)
    assert codes({"notes": "x" * 3001}, False) == {("notes", "too_long")}


def test_schema_loader_prefers_real_schema(tmp_path, monkeypatch):
    real = tmp_path / "rating.schema.json"
    real.write_text('{"type": "object", "required": ["marker"]}')
    monkeypatch.setattr(rating_mod, "REAL_SCHEMA", real)
    rating_mod.load_schema.cache_clear()
    try:
        assert rating_mod.load_schema()["required"] == ["marker"]
    finally:
        monkeypatch.undo()
        rating_mod.load_schema.cache_clear()
    assert "$defs" in rating_mod.load_schema() or "properties" in rating_mod.load_schema()
