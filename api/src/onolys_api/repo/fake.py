"""In-memory `Repo` with the same semantics as FirestoreRepo. Records `session_status` writes."""

import copy
import threading
from datetime import datetime
from typing import Any

from onolys_core.transcript import Transcript

from onolys_api.repo import large
from onolys_api.repo.base import (
    Claim,
    ConflictError,
    NotFoundError,
    Page,
    ReserveOutcome,
    StartOutcome,
    decide_claim,
)
from onolys_api.repo.firestore import (
    DRAFT_ID,
    MAX_LIMIT,
    _decode_cursor,
    _encode_cursor,
    _idem_id,
)
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
    SessionError,
    SessionStatusDoc,
    TranscriptDoc,
    UsageDoc,
    UserDoc,
    utcnow,
)
from onolys_api.storage.base import BlobStore


def _set_path(d: dict[str, Any], dotted: str, value: Any) -> None:
    *parents, leaf = dotted.split(".")
    for p in parents:
        d = d.setdefault(p, {})
    d[leaf] = value


class FakeRepo:
    def __init__(self, blobs: BlobStore) -> None:
        self._blobs = blobs
        self._docs: dict[str, dict[str, Any]] = {}  # full path -> stored dict
        self.status_writes: list[tuple[str, str, dict[str, Any]]] = []
        self._claim_lock = threading.Lock()

    # ---- storage primitives ----

    def _put(self, path: str, data: dict[str, Any]) -> None:
        self._docs[path] = copy.deepcopy(data)

    def _get(self, path: str) -> dict[str, Any] | None:
        d = self._docs.get(path)
        return copy.deepcopy(d) if d is not None else None

    def _create(self, path: str, data: dict[str, Any]) -> None:
        if path in self._docs:
            raise ConflictError()
        self._put(path, data)

    def _owned(self, path: str, uid: str, missing_ok: bool = False) -> dict[str, Any] | None:
        d = self._get(path)
        if d is None:
            if missing_ok:
                return None
            raise NotFoundError()
        if d.get("uid") != uid:
            raise NotFoundError()
        return d

    def _children(self, sid: str, kind: str) -> list[tuple[str, dict[str, Any]]]:
        prefix = f"sessions/{sid}/{kind}/"
        return [
            (p.removeprefix(prefix), copy.deepcopy(d))
            for p, d in self._docs.items()
            if p.startswith(prefix)
        ]

    @staticmethod
    def _load[M: Doc](model: type[M], doc_id: str, data: dict[str, Any]) -> M:
        return model.model_validate({**data, "id": doc_id})

    def _own(self, uid: str, sid: str) -> None:
        self._owned(f"sessions/{sid}", uid)

    def _own_open(self, uid: str, sid: str) -> None:
        """Owned and not being deleted: the guard of every write that creates a child doc."""
        if self._owned(f"sessions/{sid}", uid).get("state") == "deleting":
            raise NotFoundError()

    def _guarded(self, uid: str, sid: str, pointer) -> None:
        """Re-check after a blob write: a DELETE in between must not keep the blob."""
        try:
            self._own_open(uid, sid)
        except NotFoundError:
            if pointer is not None:
                self._blobs.delete(pointer.key)
            raise

    def _record_status(self, uid: str, sid: str) -> None:
        self.status_writes.append((uid, sid, copy.deepcopy(self._docs[f"session_status/{sid}"])))

    def paths(self, sid: str) -> list[str]:
        """Every stored path of one session (doc, subcollections, status): for deletion checks."""
        return sorted(
            p
            for p in self._docs
            if p in (f"sessions/{sid}", f"session_status/{sid}") or p.startswith(f"sessions/{sid}/")
        )

    # ---- users ----

    def get_user(self, uid: str) -> UserDoc | None:
        d = self._get(f"users/{uid}")
        return self._load(UserDoc, uid, d) if d is not None else None

    def ensure_user(self, uid: str) -> UserDoc:
        d = self._get(f"users/{uid}")
        if d is None:
            doc = UserDoc(id=uid)
            self._put(f"users/{uid}", doc.to_store())
            return doc
        return self._load(UserDoc, uid, d)

    # ---- sessions ----

    def create_session(
        self, uid: str, sid: str, session: SessionDoc, status: SessionStatusDoc
    ) -> None:
        if session.uid != uid or status.uid != uid:
            raise ValueError("document uid does not match the caller")
        if f"sessions/{sid}" in self._docs or f"session_status/{sid}" in self._docs:
            raise ConflictError()
        self._put(f"sessions/{sid}", session.to_store())
        self._put(f"session_status/{sid}", status.to_store())
        self._record_status(uid, sid)

    def get_session(self, uid: str, sid: str) -> SessionDoc:
        return self._load(SessionDoc, sid, self._owned(f"sessions/{sid}", uid))

    def get_status(self, uid: str, sid: str) -> SessionStatusDoc:
        return self._load(SessionStatusDoc, sid, self._owned(f"session_status/{sid}", uid))

    def update_session(
        self, uid: str, sid: str, fields: dict[str, Any], status: dict[str, Any] | None = None
    ) -> None:
        doc = self._owned(f"sessions/{sid}", uid)
        now = utcnow()
        for k, v in {**fields, "updated_at": now}.items():
            _set_path(doc, k, v)
        self._put(f"sessions/{sid}", doc)
        if status is not None:
            st = self._get(f"session_status/{sid}") or {}
            st.update({**status, "uid": uid, "updated_at": now})
            self._put(f"session_status/{sid}", st)
            self._record_status(uid, sid)

    def list_sessions(
        self, uid: str, limit: int = 20, cursor: str | None = None
    ) -> Page[SessionDoc]:
        limit = max(1, min(limit, MAX_LIMIT))
        mine = sorted(
            (
                (p.removeprefix("sessions/"), d)
                for p, d in self._docs.items()
                if p.count("/") == 1 and p.startswith("sessions/") and d.get("uid") == uid
            ),
            key=lambda t: (t[1]["created_at"], t[0]),
            reverse=True,
        )
        if cursor:
            after = _decode_cursor(cursor)
            self._owned(f"sessions/{after}", uid)
            ids = [i for i, _ in mine]
            mine = mine[ids.index(after) + 1 :] if after in ids else []
        page = [self._load(SessionDoc, i, copy.deepcopy(d)) for i, d in mine[: limit + 1]]
        more = len(page) > limit
        items = page[:limit]
        return Page(items, _encode_cursor(items[-1].id) if more and items else None)

    def list_stale_sessions(
        self, state: str, before: datetime, limit: int = 50
    ) -> list[SessionDoc]:
        stale = sorted(
            (
                (p.removeprefix("sessions/"), d)
                for p, d in self._docs.items()
                if p.count("/") == 1 and p.startswith("sessions/")
                and d.get("state") == state and d["updated_at"] < before
            ),
            key=lambda t: (t[1]["updated_at"], t[0]),
        )  # fmt: skip
        return [self._load(SessionDoc, i, copy.deepcopy(d)) for i, d in stale[: max(1, limit)]]

    def fail_stale_session(
        self, uid: str, sid: str, state: str, before: datetime, error: SessionError
    ) -> bool:
        with self._claim_lock:  # the fake's "transaction"
            sess = self._owned(f"sessions/{sid}", uid)
            assert sess is not None
            if sess.get("state") != state or sess["updated_at"] >= before:
                return False
            now = utcnow()
            sess.update(state="failed", error=error.model_dump(), updated_at=now)
            if error.step and error.step in (sess.get("steps") or {}):
                for k, v in (("status", "failed"), ("ended", now), ("error", error.code)):
                    _set_path(sess, f"steps.{error.step}.{k}", v)
            self._put(f"sessions/{sid}", sess)
            status = self._get(f"session_status/{sid}") or {}
            status.update(state="failed", error_code=error.code, uid=uid, updated_at=now)
            self._put(f"session_status/{sid}", status)
            self._record_status(uid, sid)
            return True

    def delete_session(self, uid: str, sid: str) -> bool:
        s = self._owned(f"sessions/{sid}", uid, missing_ok=True)
        st = self._owned(f"session_status/{sid}", uid, missing_ok=True)
        if s is not None:
            for p in [p for p in self._docs if p.startswith(f"sessions/{sid}/")]:
                del self._docs[p]
            del self._docs[f"sessions/{sid}"]
        if st is not None:
            del self._docs[f"session_status/{sid}"]
        return s is not None or st is not None

    # ---- recordings ----

    def add_recording(self, uid: str, sid: str, rid: str, rec: RecordingDoc) -> None:
        self._own_open(uid, sid)
        self._put(f"sessions/{sid}/recordings/{rid}", rec.to_store())

    def list_recordings(self, uid: str, sid: str) -> list[RecordingDoc]:
        self._own(uid, sid)
        return [self._load(RecordingDoc, i, d) for i, d in self._children(sid, "recordings")]

    # ---- transcripts ----

    def put_transcript(self, uid: str, sid: str, tid: str, transcript: Transcript) -> None:
        self._own_open(uid, sid)
        pointer = large.pack(
            self._blobs, large.transcript_key(uid, sid), transcript.model_dump(mode="json")
        )
        doc = TranscriptDoc(transcript=None if pointer else transcript, pointer=pointer)
        self._guarded(uid, sid, pointer)
        self._put(f"sessions/{sid}/transcripts/{tid}", doc.to_store())

    def get_transcript(self, uid: str, sid: str, tid: str, resolve: bool = True) -> TranscriptDoc:
        self._own(uid, sid)
        d = self._get(f"sessions/{sid}/transcripts/{tid}")
        if d is None:
            raise NotFoundError()
        doc = self._load(TranscriptDoc, tid, d)
        if resolve and doc.pointer is not None:
            doc.transcript = Transcript.model_validate(large.unpack(self._blobs, doc.pointer))
        return doc

    # ---- ratings ----

    def put_rating_revision(self, uid: str, sid: str, rating_id: str, doc: RatingDoc) -> None:
        if rating_id == DRAFT_ID:
            raise ValueError("reserved rating id")
        self._own_open(uid, sid)
        self._create(f"sessions/{sid}/ratings/{rating_id}", doc.to_store())

    def get_rating(self, uid: str, sid: str, rating_id: str) -> RatingDoc:
        self._own(uid, sid)
        d = None if rating_id == DRAFT_ID else self._get(f"sessions/{sid}/ratings/{rating_id}")
        if d is None:
            raise NotFoundError()
        return self._load(RatingDoc, rating_id, d)

    def latest_rating(self, uid: str, sid: str) -> RatingDoc | None:
        self._own(uid, sid)
        revs = [(i, d) for i, d in self._children(sid, "ratings") if i != DRAFT_ID]
        if not revs:
            return None
        i, d = max(revs, key=lambda t: (t[1]["created_at"], t[0]))
        return self._load(RatingDoc, i, d)

    def put_rating_draft(self, uid: str, sid: str, draft: RatingDraftDoc) -> None:
        self._own_open(uid, sid)
        self._put(f"sessions/{sid}/ratings/{DRAFT_ID}", draft.to_store())

    def get_rating_draft(self, uid: str, sid: str) -> RatingDraftDoc | None:
        self._own(uid, sid)
        d = self._get(f"sessions/{sid}/ratings/{DRAFT_ID}")
        return self._load(RatingDraftDoc, DRAFT_ID, d) if d is not None else None

    # ---- runs ----

    def create_run(self, uid: str, sid: str, run_id: str, run: RunDoc) -> None:
        if run.uid != uid:
            raise ValueError("document uid does not match the caller")
        self._own_open(uid, sid)
        self._create(f"sessions/{sid}/runs/{run_id}", run.to_store())

    def get_run(self, uid: str, sid: str, run_id: str) -> RunDoc:
        self._own(uid, sid)
        d = self._get(f"sessions/{sid}/runs/{run_id}")
        if d is None:
            raise NotFoundError()
        return self._load(RunDoc, run_id, d)

    def update_run(self, uid: str, sid: str, run_id: str, fields: dict[str, Any]) -> None:
        self._own(uid, sid)
        d = self._get(f"sessions/{sid}/runs/{run_id}")
        if d is None:
            raise NotFoundError()
        for k, v in fields.items():
            _set_path(d, k, v)
        self._put(f"sessions/{sid}/runs/{run_id}", d)

    def claim_step(self, uid: str, sid: str, step: str, now: datetime, lease_s: float) -> Claim:
        with self._claim_lock:
            doc = self._owned(f"sessions/{sid}", uid)
            rec = (doc.get("steps") or {}).get(step) or {}
            claim = decide_claim(
                rec.get("status"), rec.get("started"), rec.get("attempts", 0), now, lease_s
            )
            if claim.outcome == "claimed":
                for k, v in (
                    ("status", "running"),
                    ("attempts", claim.attempts),
                    ("started", now),
                    ("error", None),
                ):
                    _set_path(doc, f"steps.{step}.{k}", v)
                self._put(f"sessions/{sid}", doc)
            return claim

    def claim_run(self, uid: str, sid: str, run_id: str, now: datetime, lease_s: float) -> Claim:
        self._own(uid, sid)
        with self._claim_lock:
            d = self._get(f"sessions/{sid}/runs/{run_id}")
            if d is None:
                raise NotFoundError()
            claim = decide_claim(
                d.get("status"), d.get("started"), d.get("attempts", 0), now, lease_s
            )
            if claim.outcome == "claimed":
                d.update(status="running", attempts=claim.attempts, started=now, error=None)
                self._put(f"sessions/{sid}/runs/{run_id}", d)
            return claim

    def list_runs(self, uid: str, sid: str) -> list[RunDoc]:
        self._own(uid, sid)
        return sorted(
            (self._load(RunDoc, i, d) for i, d in self._children(sid, "runs")),
            key=lambda r: (r.started or utcnow(), r.run_id),
        )

    def get_run_by_id(self, uid: str, run_id: str) -> RunDoc:
        for path, d in self._docs.items():
            parts = path.split("/")
            if (
                len(parts) == 4
                and parts[0] == "sessions"
                and parts[2] == "runs"
                and d.get("uid") == uid
                and d.get("run_id") == run_id
            ):
                return self._load(RunDoc, parts[3], copy.deepcopy(d))
        raise NotFoundError()

    # ---- reports ----

    def put_report(self, uid: str, sid: str, report_id: str, doc: ReportDoc) -> None:
        self._own_open(uid, sid)
        pointer = large.pack(self._blobs, large.report_key(uid, sid, report_id), doc.report or {})
        stored = doc.model_copy(
            update={"report": None if pointer else doc.report, "pointer": pointer}
        )
        self._guarded(uid, sid, pointer)
        self._put(f"sessions/{sid}/reports/{report_id}", stored.to_store())

    def _resolve_report(self, doc: ReportDoc, resolve: bool) -> ReportDoc:
        if resolve and doc.pointer is not None:
            doc.report = large.unpack(self._blobs, doc.pointer)
        return doc

    def get_report(self, uid: str, sid: str, report_id: str, resolve: bool = True) -> ReportDoc:
        self._own(uid, sid)
        d = self._get(f"sessions/{sid}/reports/{report_id}")
        if d is None:
            raise NotFoundError()
        return self._resolve_report(self._load(ReportDoc, report_id, d), resolve)

    def get_report_by_version(
        self, uid: str, sid: str, version: int, resolve: bool = True
    ) -> ReportDoc:
        self._own(uid, sid)
        for i, d in self._children(sid, "reports"):
            if d.get("version") == version:
                return self._resolve_report(self._load(ReportDoc, i, d), resolve)
        raise NotFoundError()

    def list_reports(self, uid: str, sid: str) -> list[ReportDoc]:
        self._own(uid, sid)
        return sorted(
            (self._load(ReportDoc, i, d) for i, d in self._children(sid, "reports")),
            key=lambda r: r.version,
        )

    # ---- api keys ----

    def get_api_key(self, keyid: str) -> ApiKeyDoc | None:
        d = self._get(f"api_keys/{keyid}")
        return self._load(ApiKeyDoc, keyid, d) if d is not None else None

    def create_api_key(self, uid: str, keyid: str, doc: ApiKeyDoc) -> None:
        if doc.uid != uid:
            raise ValueError("document uid does not match the caller")
        self._create(f"api_keys/{keyid}", doc.to_store())

    def active_api_key(self, uid: str) -> ApiKeyDoc | None:
        for path, d in self._docs.items():
            if path.startswith("api_keys/") and d.get("uid") == uid and d.get("revoked_at") is None:
                return self._load(ApiKeyDoc, path.removeprefix("api_keys/"), copy.deepcopy(d))
        return None

    def _update_key(self, uid: str, keyid: str, **fields: datetime) -> None:
        d = self._owned(f"api_keys/{keyid}", uid)
        d.update(fields)
        self._put(f"api_keys/{keyid}", d)

    def revoke_api_key(self, uid: str, keyid: str, at: datetime) -> None:
        self._update_key(uid, keyid, revoked_at=at)

    def mark_api_key_used(self, uid: str, keyid: str, at: datetime) -> None:
        self._update_key(uid, keyid, last_used_at=at)

    # ---- usage + idempotency ----

    def get_usage(self, uid: str, date: str) -> UsageDoc:
        d = self._get(f"usage/{uid}_{date}")
        return self._load(UsageDoc, f"{uid}_{date}", d) if d else UsageDoc(uid=uid, date=date)

    def add_usage(self, uid: str, date: str, runs: int = 0, tokens: int = 0) -> UsageDoc:
        path = f"usage/{uid}_{date}"
        d = self._get(path) or {"uid": uid, "date": date, "runs": 0, "tokens": 0}
        d["runs"] += runs
        d["tokens"] += tokens
        self._put(path, d)
        return self._load(UsageDoc, f"{uid}_{date}", d)

    def reserve_run(self, uid: str, date: str, cap: int, max_active: int) -> ReserveOutcome:
        with self._claim_lock:
            user = self._get(f"users/{uid}") or {}
            usage = self._get(f"usage/{uid}_{date}") or {"uid": uid, "date": date, "runs": 0}
            active = user.get("active_runs", 0)
            eff_cap = user.get("daily_cap")
            eff_active = user.get("max_active_runs")
            if usage.get("runs", 0) >= (cap if eff_cap is None else eff_cap):
                return "daily_cap"
            if active >= (max_active if eff_active is None else eff_active):
                return "concurrent"
            self._put(f"usage/{uid}_{date}", {**usage, "runs": usage.get("runs", 0) + 1})
            self._put(f"users/{uid}", {**user, "active_runs": active + 1})
            return "ok"

    def start_first_run(
        self, uid: str, sid: str, run_id: str, date: str, cap: int, max_active: int,
        code_version: str, start_progress: int,
    ) -> StartOutcome:  # fmt: skip
        with self._claim_lock:  # the fake's "transaction"
            sess = self._owned(f"sessions/{sid}", uid)
            assert sess is not None
            if sess.get("first_run_id"):
                return "already"
            if sess.get("state") != "awaiting_input" or not all(
                sess.get(f) for f in ("transcript_ready", "speaker_confirmed", "rating_submitted")
            ):
                return "not_ready"
            status = self._get(f"session_status/{sid}") or {}
            user = self._get(f"users/{uid}") or {}
            usage = self._get(f"usage/{uid}_{date}") or {"uid": uid, "date": date, "runs": 0}
            now = utcnow()
            eff_cap, eff_active = user.get("daily_cap"), user.get("max_active_runs")
            outcome: StartOutcome | None = None
            if usage.get("runs", 0) >= (cap if eff_cap is None else eff_cap):
                outcome = "daily_cap"
            elif user.get("active_runs", 0) >= (max_active if eff_active is None else eff_active):
                outcome = "concurrent"
            if outcome is not None:
                err = {"code": "daily_cap_reached", "step": None}
                self._put(f"sessions/{sid}", {**sess, "error": err, "updated_at": now})
                self._put(
                    f"session_status/{sid}",
                    {**status, "error_code": "daily_cap_reached", "updated_at": now},
                )
                self._record_status(uid, sid)
                return outcome
            revs = [(i, d) for i, d in self._children(sid, "ratings") if i != DRAFT_ID]
            rating_id = max(revs, key=lambda t: (t[1]["created_at"], t[0]))[0] if revs else None
            run = RunDoc(
                uid=uid, session_id=sid, run_id=run_id, n_runs=sess.get("n_runs", 1),
                preset=sess.get("preset"), rating_id=rating_id,
                stt=sess.get("stt"), code_version=code_version, cap_date=date,
            )  # fmt: skip
            self._create(f"sessions/{sid}/runs/{run_id}", run.to_store())
            self._put(f"usage/{uid}_{date}", {**usage, "runs": usage.get("runs", 0) + 1})
            self._put(f"users/{uid}", {**user, "active_runs": user.get("active_runs", 0) + 1})
            self._put(
                f"sessions/{sid}",
                {**sess, "first_run_id": run_id, "state": "running", "step": None, "error": None,
                 "updated_at": now},
            )  # fmt: skip
            self._put(
                f"session_status/{sid}",
                {**status, "state": "running", "step": None, "error_code": None,
                 "progress": max(status.get("progress", 0), start_progress), "updated_at": now},
            )  # fmt: skip
            self._record_status(uid, sid)
            return "started"

    def release_run(self, uid: str, date: str, refund: bool) -> None:
        with self._claim_lock:
            user = self._get(f"users/{uid}") or {}
            if user.get("active_runs", 0) > 0:
                self._put(f"users/{uid}", {**user, "active_runs": user["active_runs"] - 1})
            usage = self._get(f"usage/{uid}_{date}")
            if refund and usage and usage.get("runs", 0) > 0:
                self._put(f"usage/{uid}_{date}", {**usage, "runs": usage["runs"] - 1})

    def get_idempotency(self, uid: str, key: str) -> IdempotencyDoc | None:
        path = f"idempotency/{_idem_id(uid, key)}"
        d = self._owned(path, uid, missing_ok=True)
        return self._load(IdempotencyDoc, _idem_id(uid, key), d) if d is not None else None

    def put_idempotency(self, uid: str, key: str, doc: IdempotencyDoc) -> bool:
        path = f"idempotency/{_idem_id(uid, key)}"
        if path in self._docs:
            return False
        self._put(path, {**doc.to_store(), "uid": uid})
        return True

    def delete_idempotency(self, uid: str, key: str) -> None:
        path = f"idempotency/{_idem_id(uid, key)}"
        if self._owned(path, uid, missing_ok=True) is not None:
            del self._docs[path]
