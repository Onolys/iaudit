"""Repo contract suite: identical tests against FakeRepo and the Firestore emulator."""

import os
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from onolys_core.transcript import Transcript, Turn

from onolys_api.repo.base import ConflictError, NotFoundError
from onolys_api.repo.fake import FakeRepo
from onolys_api.repo.large import MAX_INLINE_BYTES
from onolys_api.repo.models import (
    ApiKeyDoc,
    IdempotencyDoc,
    RatingDoc,
    RatingDraftDoc,
    RecordingDoc,
    ReportDoc,
    RunDoc,
    SessionDoc,
    SessionStatusDoc,
    StepRecord,
)
from onolys_api.storage.fake import FakeBlobStore

HAS_EMULATOR = bool(os.environ.get("FIRESTORE_EMULATOR_HOST"))


@pytest.fixture(
    params=[
        "fake",
        pytest.param(
            "firestore",
            marks=[
                pytest.mark.integration,
                pytest.mark.skipif(not HAS_EMULATOR, reason="FIRESTORE_EMULATOR_HOST not set"),
            ],
        ),
    ]
)
def blobs(request, tmp_path):
    return FakeBlobStore(tmp_path / "blobs", bucket="test-bucket")


@pytest.fixture(params=["fake", pytest.param("firestore", marks=pytest.mark.integration)])
def repo(request, blobs):
    if request.param == "fake":
        return FakeRepo(blobs)
    if not HAS_EMULATOR:
        pytest.skip("FIRESTORE_EMULATOR_HOST not set")
    from google.auth.credentials import AnonymousCredentials
    from google.cloud import firestore

    from onolys_api.repo.firestore import FirestoreRepo

    client = firestore.Client(project="demo-onolys", credentials=AnonymousCredentials())
    return FirestoreRepo(client, blobs)


def session_paths(repo, sid):
    """Enumerate every remaining doc of a session: doc, status, all subcollections."""
    if isinstance(repo, FakeRepo):
        return repo.paths(sid)
    client = repo._client
    out = []
    ref = client.collection("sessions").document(sid)
    if ref.get().exists:
        out.append(ref.path)
    if client.collection("session_status").document(sid).get().exists:
        out.append(f"session_status/{sid}")
    for coll in ref.collections():
        out += [d.reference.path for d in coll.stream()]
    return out


def new_ids():
    return f"u-{uuid.uuid4().hex[:10]}", f"s-{uuid.uuid4().hex[:10]}"


def mk_session(uid, title="t", created_at=None):
    now = created_at or datetime.now(UTC)
    return (
        SessionDoc(uid=uid, title=title, created_at=now, updated_at=now),
        SessionStatusDoc(uid=uid, updated_at=now),
    )


def seed(repo, uid=None, sid=None, **kw):
    uid, sid = uid or new_ids()[0], sid or new_ids()[1]
    s, st = mk_session(uid, **kw)
    repo.create_session(uid, sid, s, st)
    return uid, sid


def transcript(n=3, text="hello"):
    return Transcript(
        turns=[Turn(id=f"t{i}", speaker="A" if i % 2 else "B", text=text) for i in range(n)],
        language="en",
        duration_ms=1000,
    )


# ---- sessions + status ----


def test_session_roundtrip_and_status_created_with_session(repo):
    uid, sid = seed(repo, title="mine")
    s = repo.get_session(uid, sid)
    assert s.id == sid and s.uid == uid and s.title == "mine" and s.state == "created"
    st = repo.get_status(uid, sid)
    assert st.uid == uid and st.state == "created" and st.progress == 0


def test_create_session_twice_conflicts(repo):
    uid, sid = seed(repo)
    s, st = mk_session(uid)
    with pytest.raises(ConflictError):
        repo.create_session(uid, sid, s, st)


def test_create_session_rejects_foreign_uid_in_doc(repo):
    uid, sid = new_ids()
    s, st = mk_session("someone-else")
    with pytest.raises(ValueError):
        repo.create_session(uid, sid, s, st)


def test_update_session_mirrors_status_and_dotted_fields(repo):
    uid, sid = seed(repo)
    step = StepRecord(status="running", attempts=1).model_dump(mode="python")
    repo.update_session(
        uid,
        sid,
        {"state": "validating", "steps.validate": step, "transcript_ready": True},
        status={"state": "validating", "progress": 10, "transcript_ready": True},
    )
    s = repo.get_session(uid, sid)
    assert s.state == "validating" and s.transcript_ready is True
    assert s.steps["validate"].status == "running" and s.steps["validate"].attempts == 1
    assert s.updated_at is not None
    st = repo.get_status(uid, sid)
    assert st.state == "validating" and st.progress == 10 and st.transcript_ready is True


def test_status_doc_holds_no_phi_fields(repo):
    uid, sid = seed(repo, title="secret title")
    keys = set(repo.get_status(uid, sid).model_dump())
    assert keys == {
        "id",
        "uid",
        "state",
        "step",
        "progress",
        "error_code",
        "latest_report_version",
        "updated_at",
        "transcript_ready",
        "speaker_confirmed",
        "rating_submitted",
        "has_rating",
    }


def test_list_sessions_newest_first_paged_and_uid_scoped(repo):
    uid, _ = new_ids()
    other_uid, _ = new_ids()
    base = datetime.now(UTC)
    sids = []
    for i in range(5):
        sid = f"s-{i}-{uuid.uuid4().hex[:6]}"
        seed(repo, uid=uid, sid=sid, title=f"t{i}", created_at=base + timedelta(seconds=i))
        sids.append(sid)
    seed(repo, uid=other_uid, title="other")
    p1 = repo.list_sessions(uid, limit=2)
    assert [s.id for s in p1.items] == [sids[4], sids[3]]
    assert p1.next_cursor
    p2 = repo.list_sessions(uid, limit=2, cursor=p1.next_cursor)
    assert [s.id for s in p2.items] == [sids[2], sids[1]]
    p3 = repo.list_sessions(uid, limit=2, cursor=p2.next_cursor)
    assert [s.id for s in p3.items] == [sids[0]]
    assert p3.next_cursor is None
    assert all(s.uid == uid for s in p1.items + p2.items + p3.items)


def test_list_sessions_bad_cursor_is_not_found(repo):
    uid, _ = new_ids()
    with pytest.raises(NotFoundError):
        repo.list_sessions(uid, limit=2, cursor="bm9wZQ")  # "nope"


# ---- children ----


def test_recordings_roundtrip(repo):
    uid, sid = seed(repo)
    repo.add_recording(
        uid,
        sid,
        "r1",
        RecordingDoc(gcs_uri="gs://b/x", size=10, duration_ms=5, format="wav", sha256="ab"),
    )
    recs = repo.list_recordings(uid, sid)
    assert [r.id for r in recs] == ["r1"] and recs[0].format == "wav"


def test_transcript_small_stays_inline(repo, blobs):
    uid, sid = seed(repo)
    repo.put_transcript(uid, sid, "tr1", transcript())
    raw = repo.get_transcript(uid, sid, "tr1", resolve=False)
    assert raw.pointer is None and raw.transcript is not None
    assert repo.get_transcript(uid, sid, "tr1").transcript == transcript()
    assert blobs.list_keys("") == []


def test_transcript_over_500kb_goes_to_blob_with_pointer_roundtrip(repo, blobs):
    uid, sid = seed(repo)
    big = transcript(n=60, text="x" * 10_000)
    assert len(big.model_dump_json()) > MAX_INLINE_BYTES
    repo.put_transcript(uid, sid, "tr1", big)
    raw = repo.get_transcript(uid, sid, "tr1", resolve=False)
    assert raw.transcript is None and raw.pointer is not None
    assert raw.pointer.key == f"{uid}/{sid}/transcript.json"
    assert raw.pointer.uri == f"gs://test-bucket/{uid}/{sid}/transcript.json"
    assert raw.pointer.size_bytes > MAX_INLINE_BYTES
    assert blobs.exists(raw.pointer.key)
    assert repo.get_transcript(uid, sid, "tr1").transcript == big


def test_ratings_revisions_draft_and_latest(repo):
    uid, sid = seed(repo)
    assert repo.latest_rating(uid, sid) is None
    assert repo.get_rating_draft(uid, sid) is None
    t0 = datetime.now(UTC)
    repo.put_rating_revision(
        uid, sid, "rt1", RatingDoc(card={"a": 1}, no_rating=False, created_at=t0)
    )
    repo.put_rating_revision(
        uid,
        sid,
        "rt2",
        RatingDoc(card={"a": 2}, no_rating=False, created_at=t0 + timedelta(seconds=1)),
    )
    repo.put_rating_draft(uid, sid, RatingDraftDoc(card={"d": 1}, updated_at=t0))
    repo.put_rating_draft(uid, sid, RatingDraftDoc(card={"d": 2}, updated_at=t0))
    latest = repo.latest_rating(uid, sid)
    assert latest.id == "rt2" and latest.card == {"a": 2}
    assert repo.get_rating(uid, sid, "rt1").card == {"a": 1}
    assert repo.get_rating_draft(uid, sid).card == {"d": 2}
    with pytest.raises(NotFoundError):
        repo.get_rating(uid, sid, "draft")  # the draft doc is not a revision


def test_runs_create_update_list_and_lookup_by_id(repo):
    uid, sid = seed(repo)
    run_id = f"run-{uuid.uuid4().hex[:8]}"
    now = datetime.now(UTC)
    repo.create_run(
        uid,
        sid,
        run_id,
        RunDoc(uid=uid, session_id=sid, run_id=run_id, n_runs=1, preset="p", started=now),
    )
    with pytest.raises(ConflictError):
        repo.create_run(
            uid, sid, run_id, RunDoc(uid=uid, session_id=sid, run_id=run_id, started=now)
        )
    repo.update_run(uid, sid, run_id, {"status": "done", "stage": "assemble"})
    r = repo.get_run(uid, sid, run_id)
    assert r.status == "done" and r.stage == "assemble"
    assert [x.run_id for x in repo.list_runs(uid, sid)] == [run_id]
    by_id = repo.get_run_by_id(uid, run_id)
    assert by_id.session_id == sid
    with pytest.raises(NotFoundError):
        repo.get_run_by_id(new_ids()[0], run_id)


def test_reports_small_inline_big_pointer_and_by_version(repo, blobs):
    uid, sid = seed(repo)
    now = datetime.now(UTC)
    small = ReportDoc(version=1, run_id="r1", report={"k": "v"}, created_at=now)
    repo.put_report(uid, sid, "rp1", small)
    big_payload = {"blob": "y" * (MAX_INLINE_BYTES + 10)}
    repo.put_report(
        uid,
        sid,
        "rp2",
        ReportDoc(
            version=2,
            run_id="r2",
            report=big_payload,
            created_at=now + timedelta(seconds=1),
        ),
    )
    raw2 = repo.get_report(uid, sid, "rp2", resolve=False)
    assert raw2.report is None and raw2.pointer.key == f"{uid}/{sid}/reports/rp2.json"
    assert repo.get_report(uid, sid, "rp2").report == big_payload
    assert repo.get_report(uid, sid, "rp1", resolve=False).pointer is None
    assert [r.version for r in repo.list_reports(uid, sid)] == [1, 2]
    assert repo.get_report_by_version(uid, sid, 2).id == "rp2"
    with pytest.raises(NotFoundError):
        repo.get_report_by_version(uid, sid, 3)


def test_delete_session_removes_doc_status_and_every_subcollection(repo):
    uid, sid = seed(repo)
    now = datetime.now(UTC)
    repo.add_recording(uid, sid, "r1", RecordingDoc(gcs_uri="gs://b/x"))
    repo.put_transcript(uid, sid, "tr1", transcript())
    repo.put_rating_revision(uid, sid, "rt1", RatingDoc(card={}, created_at=now))
    repo.put_rating_draft(uid, sid, RatingDraftDoc(card={}, updated_at=now))
    repo.create_run(uid, sid, "run1", RunDoc(uid=uid, session_id=sid, run_id="run1", started=now))
    repo.put_report(uid, sid, "rp1", ReportDoc(version=1, run_id="run1", report={}, created_at=now))
    assert repo.delete_session(uid, sid) is True
    with pytest.raises(NotFoundError):
        repo.get_session(uid, sid)
    with pytest.raises(NotFoundError):
        repo.get_status(uid, sid)
    assert session_paths(repo, sid) == []
    assert repo.delete_session(uid, sid) is False  # idempotent for retried cleanup


# ---- users / api keys / usage / idempotency ----


def test_users_ensure_is_idempotent(repo):
    uid, _ = new_ids()
    assert repo.get_user(uid) is None
    u1 = repo.ensure_user(uid)
    u2 = repo.ensure_user(uid)
    assert u1.created_at == u2.created_at and u1.expiry_days is None


def test_api_keys_one_active_revoke_and_lookup(repo):
    uid, _ = new_ids()
    kid = uuid.uuid4().hex[:8]
    now = datetime.now(UTC)
    repo.create_api_key(uid, kid, ApiKeyDoc(uid=uid, hash="h" * 64, created=now))
    with pytest.raises(ConflictError):
        repo.create_api_key(uid, kid, ApiKeyDoc(uid=uid, hash="h" * 64, created=now))
    assert repo.get_api_key(kid).uid == uid  # unscoped: auth bootstrap by key id
    assert repo.active_api_key(uid).id == kid
    repo.mark_api_key_used(uid, kid, now)
    assert repo.get_api_key(kid).last_used_at is not None
    repo.revoke_api_key(uid, kid, now)
    assert repo.active_api_key(uid) is None
    assert repo.get_api_key(kid).revoked_at is not None
    assert repo.get_api_key("nope") is None


def test_usage_increments_atomically_per_uid_date(repo):
    uid, _ = new_ids()
    assert repo.get_usage(uid, "2026-11-20").runs == 0
    repo.add_usage(uid, "2026-11-20", runs=1)
    u = repo.add_usage(uid, "2026-11-20", runs=2, tokens=50)
    assert u.runs == 3 and u.tokens == 50
    assert repo.get_usage(uid, "2026-11-21").runs == 0


def test_idempotency_set_if_absent(repo):
    uid, _ = new_ids()
    now = datetime.now(UTC)
    doc = IdempotencyDoc(body_hash="b", response={"id": "s1"}, created_at=now)
    assert repo.get_idempotency(uid, "k1") is None
    assert repo.put_idempotency(uid, "k1", doc) is True
    assert repo.put_idempotency(uid, "k1", doc.model_copy(update={"body_hash": "z"})) is False
    got = repo.get_idempotency(uid, "k1")
    assert got.body_hash == "b" and got.response == {"id": "s1"}
    assert repo.get_idempotency(new_ids()[0], "k1") is None


# ---- two-user isolation: every id-addressed call returns not-found for another uid ----


def test_two_user_cross_uid_reads_and_writes_are_not_found(repo):
    a, sid = seed(repo, title="A's")
    b, _ = new_ids()
    now = datetime.now(UTC)
    repo.add_recording(a, sid, "r1", RecordingDoc(gcs_uri="gs://b/x"))
    repo.put_transcript(a, sid, "tr1", transcript())
    repo.put_rating_revision(a, sid, "rt1", RatingDoc(card={}, created_at=now))
    repo.put_rating_draft(a, sid, RatingDraftDoc(card={}, updated_at=now))
    repo.create_run(a, sid, "run1", RunDoc(uid=a, session_id=sid, run_id="run1", started=now))
    repo.put_report(a, sid, "rp1", ReportDoc(version=1, run_id="run1", report={}, created_at=now))

    calls = {
        "get_session": lambda: repo.get_session(b, sid),
        "get_status": lambda: repo.get_status(b, sid),
        "update_session": lambda: repo.update_session(b, sid, {"title": "pwn"}, status={}),
        "list_recordings": lambda: repo.list_recordings(b, sid),
        "add_recording": lambda: repo.add_recording(b, sid, "r9", RecordingDoc(gcs_uri="g")),
        "get_transcript": lambda: repo.get_transcript(b, sid, "tr1"),
        "put_transcript": lambda: repo.put_transcript(b, sid, "tr9", transcript()),
        "get_rating": lambda: repo.get_rating(b, sid, "rt1"),
        "latest_rating": lambda: repo.latest_rating(b, sid),
        "get_rating_draft": lambda: repo.get_rating_draft(b, sid),
        "put_rating_draft": lambda: repo.put_rating_draft(
            b, sid, RatingDraftDoc(card={}, updated_at=now)
        ),
        "put_rating_revision": lambda: repo.put_rating_revision(
            b, sid, "rt9", RatingDoc(card={}, created_at=now)
        ),
        "get_run": lambda: repo.get_run(b, sid, "run1"),
        "update_run": lambda: repo.update_run(b, sid, "run1", {"status": "failed"}),
        "list_runs": lambda: repo.list_runs(b, sid),
        "get_run_by_id": lambda: repo.get_run_by_id(b, "run1"),
        "get_report": lambda: repo.get_report(b, sid, "rp1"),
        "get_report_by_version": lambda: repo.get_report_by_version(b, sid, 1),
        "list_reports": lambda: repo.list_reports(b, sid),
        "delete_session": lambda: repo.delete_session(b, sid),
    }
    for call in calls.values():
        with pytest.raises(NotFoundError):
            call()
        # and NotFoundError is a 404 ApiError (never 403)
    try:
        repo.get_session(b, sid)
    except NotFoundError as e:
        assert e.status == 404 and e.details[0]["code"] == "not_found"

    assert repo.list_sessions(b).items == []
    # owner still intact after the failed attacks
    assert repo.get_session(a, sid).title == "A's"
    assert repo.get_rating_draft(a, sid) is not None
    assert repo.get_run(a, sid, "run1").status == "pending"


def test_missing_session_and_foreign_session_look_identical(repo):
    a, sid = seed(repo)
    b, missing = new_ids()
    with pytest.raises(NotFoundError) as e1:
        repo.get_session(b, sid)
    with pytest.raises(NotFoundError) as e2:
        repo.get_session(b, missing)
    assert (e1.value.status, e1.value.message, e1.value.details) == (
        e2.value.status,
        e2.value.message,
        e2.value.details,
    )


def test_fake_repo_records_session_status_writes(tmp_path):
    repo = FakeRepo(FakeBlobStore(tmp_path))
    uid, sid = seed(repo)
    repo.update_session(
        uid, sid, {"state": "uploading"}, status={"state": "uploading", "progress": 5}
    )
    repo.update_session(uid, sid, {"title": "x"})  # no status mirror, no status write
    assert [(w[2]["state"], w[2]["progress"]) for w in repo.status_writes] == [
        ("created", 0),
        ("uploading", 5),
    ]
    assert all(w[0] == uid and w[1] == sid for w in repo.status_writes)
