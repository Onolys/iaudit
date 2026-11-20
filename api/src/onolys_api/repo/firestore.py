"""Firestore-backed `Repo`. Honours FIRESTORE_DATABASE; uses the emulator when
FIRESTORE_EMULATOR_HOST is set.

uid discipline (D7): collection queries go through `_uid_query`; documents addressed by id go
through `_owned`; both raise `NotFoundError` on a foreign or missing document. A test greps this
file so no function queries without one of the helpers.
"""

import base64
import binascii
import hashlib
import os
from datetime import datetime
from typing import Any

from google.api_core.exceptions import AlreadyExists
from google.cloud import firestore
from google.cloud.firestore_v1 import FieldFilter, Increment
from onolys_core.transcript import Transcript

from onolys_api.config import Settings
from onolys_api.repo import large
from onolys_api.repo.base import ConflictError, NotFoundError, Page
from onolys_api.repo.models import (
    ApiKeyDoc,
    Doc,
    IdempotencyDoc,
    RatingDoc,
    RatingDraftDoc,
    RecordingDoc,
    ReportDoc,
    RunDoc,
    SessionDoc,
    SessionStatusDoc,
    TranscriptDoc,
    UsageDoc,
    UserDoc,
    utcnow,
)
from onolys_api.storage.base import BlobStore

DRAFT_ID = "draft"
MAX_LIMIT = 50


def make_firestore_client(settings: Settings) -> firestore.Client:
    emulator = bool(os.environ.get("FIRESTORE_EMULATOR_HOST"))
    kwargs: dict[str, Any] = {
        "project": settings.gcp_project or ("demo-onolys" if emulator else None),
        "database": settings.firestore_database or "(default)",
    }
    if emulator:
        from google.auth.credentials import AnonymousCredentials

        kwargs["credentials"] = AnonymousCredentials()
    return firestore.Client(**kwargs)


def _load[M: Doc](model: type[M], snap) -> M:
    return model.model_validate({**(snap.to_dict() or {}), "id": snap.id})


def _encode_cursor(sid: str) -> str:
    return base64.urlsafe_b64encode(sid.encode()).decode().rstrip("=")


def _decode_cursor(cursor: str) -> str:
    try:
        return base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4)).decode()
    except (binascii.Error, UnicodeDecodeError):
        raise NotFoundError() from None


def _uid_query(source, uid: str):
    """The only way a collection (or collection group) is queried: always filtered by uid."""
    return source.where(filter=FieldFilter("uid", "==", uid))


def _owned(ref, uid: str, missing_ok: bool = False):
    """Snapshot of `ref` if it exists and belongs to `uid`; else NotFoundError (or None)."""
    snap = ref.get()
    if not snap.exists:
        if missing_ok:
            return None
        raise NotFoundError()
    if (snap.to_dict() or {}).get("uid") != uid:
        raise NotFoundError()
    return snap


def _idem_id(uid: str, key: str) -> str:
    return hashlib.sha256(f"{uid}\0{key}".encode()).hexdigest()


class FirestoreRepo:
    def __init__(self, client: firestore.Client, blobs: BlobStore) -> None:
        self._client = client
        self._blobs = blobs

    # ---- ownership helpers (every id-addressed call starts here) ----

    def _top(self, name: str, doc_id: str):
        return self._client.collection(name).document(doc_id)

    def _owned_session(self, uid: str, sid: str, missing_ok: bool = False):
        ref = self._top("sessions", sid)
        return ref, _owned(ref, uid, missing_ok)

    def _owned_status(self, uid: str, sid: str, missing_ok: bool = False):
        ref = self._top("session_status", sid)
        return ref, _owned(ref, uid, missing_ok)

    def _session_ref(self, uid: str, sid: str):
        return self._owned_session(uid, sid)[0]

    # ---- users ----

    def get_user(self, uid: str) -> UserDoc | None:
        snap = self._top("users", uid).get()
        return _load(UserDoc, snap) if snap.exists else None

    def ensure_user(self, uid: str) -> UserDoc:
        ref = self._top("users", uid)
        doc = UserDoc(id=uid)
        try:
            ref.create(doc.to_store())
            return doc
        except AlreadyExists:
            return _load(UserDoc, ref.get())

    # ---- sessions ----

    def create_session(
        self, uid: str, sid: str, session: SessionDoc, status: SessionStatusDoc
    ) -> None:
        if session.uid != uid or status.uid != uid:
            raise ValueError("document uid does not match the caller")
        sref, stref = self._top("sessions", sid), self._top("session_status", sid)
        if sref.get().exists or stref.get().exists:
            raise ConflictError()
        batch = self._client.batch()
        batch.create(sref, session.to_store())
        batch.create(stref, status.to_store())
        try:
            batch.commit()
        except AlreadyExists:
            raise ConflictError() from None

    def get_session(self, uid: str, sid: str) -> SessionDoc:
        return _load(SessionDoc, self._owned_session(uid, sid)[1])

    def get_status(self, uid: str, sid: str) -> SessionStatusDoc:
        return _load(SessionStatusDoc, self._owned_status(uid, sid)[1])

    def update_session(
        self, uid: str, sid: str, fields: dict[str, Any], status: dict[str, Any] | None = None
    ) -> None:
        sref, _ = self._owned_session(uid, sid)
        now = utcnow()
        batch = self._client.batch()
        batch.update(sref, {**fields, "updated_at": now})
        if status is not None:
            stref = self._top("session_status", sid)
            batch.set(stref, {**status, "uid": uid, "updated_at": now}, merge=True)
        batch.commit()

    def list_sessions(
        self, uid: str, limit: int = 20, cursor: str | None = None
    ) -> Page[SessionDoc]:
        limit = max(1, min(limit, MAX_LIMIT))
        q = _uid_query(self._client.collection("sessions"), uid).order_by(
            "created_at", direction=firestore.Query.DESCENDING
        )
        if cursor:
            _, snap = self._owned_session(uid, _decode_cursor(cursor))
            q = q.start_after(snap)
        docs = [_load(SessionDoc, s) for s in q.limit(limit + 1).stream()]
        more = len(docs) > limit
        items = docs[:limit]
        return Page(items, _encode_cursor(items[-1].id) if more and items else None)

    def delete_session(self, uid: str, sid: str) -> bool:
        sref, ssnap = self._owned_session(uid, sid, missing_ok=True)
        stref, stsnap = self._owned_status(uid, sid, missing_ok=True)
        if ssnap is not None:
            self._client.recursive_delete(sref)
        if stsnap is not None:
            stref.delete()
        return ssnap is not None or stsnap is not None

    # ---- recordings ----

    def add_recording(self, uid: str, sid: str, rid: str, rec: RecordingDoc) -> None:
        self._session_ref(uid, sid).collection("recordings").document(rid).set(rec.to_store())

    def list_recordings(self, uid: str, sid: str) -> list[RecordingDoc]:
        coll = self._session_ref(uid, sid).collection("recordings")
        return [_load(RecordingDoc, s) for s in coll.stream()]

    # ---- transcripts (large-object rule) ----

    def put_transcript(self, uid: str, sid: str, tid: str, transcript: Transcript) -> None:
        ref = self._session_ref(uid, sid).collection("transcripts").document(tid)
        pointer = large.pack(
            self._blobs, large.transcript_key(uid, sid), transcript.model_dump(mode="json")
        )
        doc = TranscriptDoc(transcript=None if pointer else transcript, pointer=pointer)
        ref.set(doc.to_store())

    def get_transcript(self, uid: str, sid: str, tid: str, resolve: bool = True) -> TranscriptDoc:
        ref = self._session_ref(uid, sid).collection("transcripts").document(tid)
        snap = ref.get()
        if not snap.exists:
            raise NotFoundError()
        doc = _load(TranscriptDoc, snap)
        if resolve and doc.pointer is not None:
            doc.transcript = Transcript.model_validate(large.unpack(self._blobs, doc.pointer))
        return doc

    # ---- ratings ----

    def put_rating_revision(self, uid: str, sid: str, rating_id: str, doc: RatingDoc) -> None:
        if rating_id == DRAFT_ID:
            raise ValueError("reserved rating id")
        ref = self._session_ref(uid, sid).collection("ratings").document(rating_id)
        try:
            ref.create(doc.to_store())
        except AlreadyExists:
            raise ConflictError() from None

    def get_rating(self, uid: str, sid: str, rating_id: str) -> RatingDoc:
        if rating_id == DRAFT_ID:
            raise NotFoundError()
        snap = self._session_ref(uid, sid).collection("ratings").document(rating_id).get()
        if not snap.exists:
            raise NotFoundError()
        return _load(RatingDoc, snap)

    def latest_rating(self, uid: str, sid: str) -> RatingDoc | None:
        coll = self._session_ref(uid, sid).collection("ratings")
        # the draft has no created_at, so ordering by it leaves the draft out
        q = coll.order_by("created_at", direction=firestore.Query.DESCENDING).limit(1)
        snaps = [s for s in q.stream() if s.id != DRAFT_ID]
        return _load(RatingDoc, snaps[0]) if snaps else None

    def put_rating_draft(self, uid: str, sid: str, draft: RatingDraftDoc) -> None:
        ref = self._session_ref(uid, sid).collection("ratings").document(DRAFT_ID)
        ref.set(draft.to_store())

    def get_rating_draft(self, uid: str, sid: str) -> RatingDraftDoc | None:
        snap = self._session_ref(uid, sid).collection("ratings").document(DRAFT_ID).get()
        return _load(RatingDraftDoc, snap) if snap.exists else None

    # ---- runs ----

    def create_run(self, uid: str, sid: str, run_id: str, run: RunDoc) -> None:
        if run.uid != uid:
            raise ValueError("document uid does not match the caller")
        ref = self._session_ref(uid, sid).collection("runs").document(run_id)
        try:
            ref.create(run.to_store())
        except AlreadyExists:
            raise ConflictError() from None

    def _run_ref(self, uid: str, sid: str, run_id: str):
        return self._session_ref(uid, sid).collection("runs").document(run_id)

    def get_run(self, uid: str, sid: str, run_id: str) -> RunDoc:
        snap = self._run_ref(uid, sid, run_id).get()
        if not snap.exists:
            raise NotFoundError()
        return _load(RunDoc, snap)

    def update_run(self, uid: str, sid: str, run_id: str, fields: dict[str, Any]) -> None:
        ref = self._run_ref(uid, sid, run_id)
        if not ref.get().exists:
            raise NotFoundError()
        ref.update(fields)

    def list_runs(self, uid: str, sid: str) -> list[RunDoc]:
        coll = self._session_ref(uid, sid).collection("runs")
        return sorted(
            (_load(RunDoc, s) for s in coll.stream()),
            key=lambda r: (r.started or utcnow(), r.run_id),
        )

    def get_run_by_id(self, uid: str, run_id: str) -> RunDoc:
        q = _uid_query(self._client.collection_group("runs"), uid)
        for snap in q.where(filter=FieldFilter("run_id", "==", run_id)).limit(1).stream():
            return _load(RunDoc, snap)
        raise NotFoundError()

    # ---- reports (large-object rule) ----

    def put_report(self, uid: str, sid: str, report_id: str, doc: ReportDoc) -> None:
        ref = self._session_ref(uid, sid).collection("reports").document(report_id)
        payload = doc.report or {}
        pointer = large.pack(self._blobs, large.report_key(uid, sid, report_id), payload)
        stored = doc.model_copy(
            update={"report": None if pointer else doc.report, "pointer": pointer}
        )
        ref.set(stored.to_store())

    def _resolve_report(self, doc: ReportDoc, resolve: bool) -> ReportDoc:
        if resolve and doc.pointer is not None:
            doc.report = large.unpack(self._blobs, doc.pointer)
        return doc

    def get_report(self, uid: str, sid: str, report_id: str, resolve: bool = True) -> ReportDoc:
        snap = self._session_ref(uid, sid).collection("reports").document(report_id).get()
        if not snap.exists:
            raise NotFoundError()
        return self._resolve_report(_load(ReportDoc, snap), resolve)

    def get_report_by_version(
        self, uid: str, sid: str, version: int, resolve: bool = True
    ) -> ReportDoc:
        coll = self._session_ref(uid, sid).collection("reports")
        for snap in coll.where(filter=FieldFilter("version", "==", version)).limit(1).stream():
            return self._resolve_report(_load(ReportDoc, snap), resolve)
        raise NotFoundError()

    def list_reports(self, uid: str, sid: str) -> list[ReportDoc]:
        coll = self._session_ref(uid, sid).collection("reports")
        return sorted((_load(ReportDoc, s) for s in coll.stream()), key=lambda r: r.version)

    # ---- api keys ----

    def get_api_key(self, keyid: str) -> ApiKeyDoc | None:
        snap = self._top("api_keys", keyid).get()
        return _load(ApiKeyDoc, snap) if snap.exists else None

    def create_api_key(self, uid: str, keyid: str, doc: ApiKeyDoc) -> None:
        if doc.uid != uid:
            raise ValueError("document uid does not match the caller")
        try:
            self._top("api_keys", keyid).create(doc.to_store())
        except AlreadyExists:
            raise ConflictError() from None

    def active_api_key(self, uid: str) -> ApiKeyDoc | None:
        q = _uid_query(self._client.collection("api_keys"), uid)
        for snap in q.where(filter=FieldFilter("revoked_at", "==", None)).limit(1).stream():
            return _load(ApiKeyDoc, snap)
        return None

    def revoke_api_key(self, uid: str, keyid: str, at: datetime) -> None:
        ref = self._top("api_keys", keyid)
        _owned(ref, uid)
        ref.update({"revoked_at": at})

    def mark_api_key_used(self, uid: str, keyid: str, at: datetime) -> None:
        ref = self._top("api_keys", keyid)
        _owned(ref, uid)
        ref.update({"last_used_at": at})

    # ---- usage + idempotency ----

    def get_usage(self, uid: str, date: str) -> UsageDoc:
        snap = self._top("usage", f"{uid}_{date}").get()
        return _load(UsageDoc, snap) if snap.exists else UsageDoc(uid=uid, date=date)

    def add_usage(self, uid: str, date: str, runs: int = 0, tokens: int = 0) -> UsageDoc:
        ref = self._top("usage", f"{uid}_{date}")
        ref.set(
            {"uid": uid, "date": date, "runs": Increment(runs), "tokens": Increment(tokens)},
            merge=True,
        )
        return _load(UsageDoc, ref.get())

    def get_idempotency(self, uid: str, key: str) -> IdempotencyDoc | None:
        ref = self._top("idempotency", _idem_id(uid, key))
        snap = _owned(ref, uid, missing_ok=True)
        return _load(IdempotencyDoc, snap) if snap is not None else None

    def put_idempotency(self, uid: str, key: str, doc: IdempotencyDoc) -> bool:
        ref = self._top("idempotency", _idem_id(uid, key))
        try:
            ref.create({**doc.to_store(), "uid": uid})
        except AlreadyExists:
            return False
        return True
