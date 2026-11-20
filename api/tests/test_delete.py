"""Task 13: hard delete + idempotent cleanup task (PRD R7 Delete, AC8). Stub flow over HTTP.

Enumerated proof: after a full flow (audio, transcript, big report to the blob store, two runs'
artifacts, a draft + final rating) nothing under either bucket prefix and no document in any
collection or subcollection of the session remains. The delete race / mid-run cancel is deferred
(PRD), so the in-flight cases here only prove the cap slot is released exactly once.
"""

import json
import logging

import pytest
import test_run
from onolys_core.transcript import Transcript, Turn
from test_run import BigEval, Env, swap_eval

from onolys_api.adapters import FakeEvaluation
from onolys_api.jobs.delete import delete_session_data
from onolys_api.repo.base import NotFoundError

pytestmark = pytest.mark.integration
env = test_run.env  # the fake/firestore stub-flow fixture
EVENTS_LOG = "onolys_api.events"


def remaining_docs(env: Env, sid: str) -> list[str]:
    """Every doc path of the session in any collection/subcollection, plus `session_status`."""
    repo = env.repo
    if hasattr(repo, "paths"):  # FakeRepo
        return repo.paths(sid)
    out: list[str] = []

    def walk(ref) -> None:
        for coll in ref.collections():
            for d in coll.list_documents():  # includes docs that only have subcollections
                out.append(d.path)
                walk(d)

    sref = repo._client.collection("sessions").document(sid)
    if sref.get().exists:
        out.append(sref.path)
    walk(sref)
    st = repo._client.collection("session_status").document(sid)
    if st.get().exists:
        out.append(st.path)
    return out


def session_blob_keys(env: Env, sid: str) -> list[str]:
    return [
        k
        for k in env.blobs.list_keys("")
        if k.startswith((f"{env.uid}/{sid}/", f"uploads/{env.uid}/{sid}/"))
    ]


def deleted_lines(caplog) -> list[dict]:
    out = []
    for r in caplog.records:
        if r.name == EVENTS_LOG and '"event": "session_deleted"' in r.getMessage():
            out.append(json.loads(r.getMessage()))
    return out


async def rich_session(env: Env, title: str = "SENTINEL-TITLE") -> str:
    """Finished session with 2 runs, a >500 KB report (blob pointer), a draft rating."""
    swap_eval(env, BigEval())
    sid = await env.finished(title)
    r = await env.c.post(f"/v1/sessions/{sid}/runs", json={}, headers=env.h)
    assert r.status_code == 202
    env.drain()
    # a second, >500 KB transcript so the transcript object path is populated too
    big = Transcript(turns=[Turn(id=f"t{i}", speaker="A", text="x" * 10_000) for i in range(60)])
    env.repo.put_transcript(env.uid, sid, "big", big)
    await env.c.put(
        f"/v1/sessions/{sid}/rating",
        json={"final": False, "card": {"change_goal": "draft"}},
        headers=env.h,
    )
    return sid


async def test_full_flow_delete_leaves_nothing_anywhere(env, caplog):
    caplog.set_level(logging.INFO)
    sid = await rich_session(env)
    other = await env.finished("keep-me")
    before = session_blob_keys(env, sid)
    # every bucket prefix family is populated before the delete
    for part in ("/audio/original", "/audio/canonical.flac", "/transcript", "/reports/", "/runs/"):
        assert any(part in k for k in before), (part, before)
    assert len(env.repo.list_runs(env.uid, sid)) == 2
    docs = remaining_docs(env, sid)
    for coll in ("recordings", "transcripts", "ratings", "runs", "reports"):
        assert any(f"/{coll}/" in p for p in docs), (coll, docs)
    usage_before = env.counters()

    r = await env.c.delete(f"/v1/sessions/{sid}", headers=env.h)
    assert r.status_code == 204 and r.content == b""

    assert session_blob_keys(env, sid) == []
    assert remaining_docs(env, sid) == []
    with pytest.raises(NotFoundError):
        env.repo.get_session(env.uid, sid)
    with pytest.raises(NotFoundError):
        env.repo.get_status(env.uid, sid)
    # the other session and per-user counters are untouched
    assert env.repo.get_session(env.uid, other).state == "report_ready"
    assert session_blob_keys(env, other)
    assert env.counters() == usage_before

    # exactly one content-free log line
    (line,) = deleted_lines(caplog)
    assert line["session_id"] == sid and len(line["uid_hash"]) == 16 and line["request_id"]
    for secret in (env.uid, "SENTINEL-TITLE"):
        assert secret not in json.dumps(line)
    # nothing left for the cleanup task either, and it adds no second line
    env.drain()
    assert len(deleted_lines(caplog)) == 1


async def test_delete_is_404_for_other_users_and_unknown_sessions(env):
    sid = await env.finished()
    r = await env.c.delete(f"/v1/sessions/{sid}", headers=env.hb)
    assert r.status_code == 404
    assert (await env.c.delete("/v1/sessions/nope", headers=env.h)).status_code == 404
    assert env.repo.get_session(env.uid, sid).state == "report_ready"
    assert session_blob_keys(env, sid)


async def test_storage_failure_leaves_deleting_then_cleanup_task_finishes(env, caplog, monkeypatch):
    caplog.set_level(logging.INFO)
    sid = await env.finished()
    real = env.blobs.delete_prefix
    calls = {"n": 0}

    def flaky(prefix):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("injected storage failure")
        return real(prefix)

    monkeypatch.setattr(env.blobs, "delete_prefix", flaky)
    r = await env.c.delete(f"/v1/sessions/{sid}", headers=env.h)
    assert r.status_code == 503 and r.json()["details"][0]["code"] == "upstream_unavailable"
    assert env.repo.get_session(env.uid, sid).state == "deleting"
    assert env.repo.get_status(env.uid, sid).state == "deleting"
    assert deleted_lines(caplog) == []
    # blocked while deleting: reads, listing, new runs
    for method, path in (
        ("GET", f"/v1/sessions/{sid}"),
        ("GET", f"/v1/sessions/{sid}/runs"),
        ("GET", f"/v1/sessions/{sid}/reports/1"),
        ("GET", f"/v1/sessions/{sid}/transcript"),
        ("POST", f"/v1/sessions/{sid}/runs"),
    ):
        assert (await env.c.request(method, path, headers=env.h)).status_code == 404, path
    listed = (await env.c.get("/v1/sessions", headers=env.h)).json()["items"]
    assert sid not in [i["id"] for i in listed]
    assert [t.kind for t in env.q.pending] == ["delete"]

    env.drain()  # the cleanup task
    assert session_blob_keys(env, sid) == [] and remaining_docs(env, sid) == []
    assert len(deleted_lines(caplog)) == 1


async def test_firestore_failure_after_storage_is_finished_by_cleanup_and_is_idempotent(
    env, caplog, monkeypatch
):
    caplog.set_level(logging.INFO)
    sid = await env.finished()
    real = env.repo.delete_session
    calls = {"n": 0}

    def flaky(uid, s):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("injected firestore failure")
        return real(uid, s)

    monkeypatch.setattr(env.repo, "delete_session", flaky)
    assert (await env.c.delete(f"/v1/sessions/{sid}", headers=env.h)).status_code == 503
    assert session_blob_keys(env, sid) == []  # storage was already cleaned
    assert env.repo.get_session(env.uid, sid).state == "deleting"

    env.drain()
    assert remaining_docs(env, sid) == []
    assert len(deleted_lines(caplog)) == 1
    # running the cleanup again (duplicate delivery) is a clean no-op
    from onolys_api.jobs.queue import TaskPayload

    res = env.app.state.runner.handle(TaskPayload(kind="delete", uid=env.uid, sid=sid))
    assert res.status_code == 200
    assert delete_session_data(env.repo, env.blobs, env.uid, sid) is False
    assert len(deleted_lines(caplog)) == 1


async def test_client_retry_of_delete_finishes_it_and_the_task_adds_no_second_line(
    env, caplog, monkeypatch
):
    caplog.set_level(logging.INFO)
    sid = await env.finished()
    real = env.blobs.delete_prefix
    calls = {"n": 0}

    def flaky(prefix):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("injected")
        return real(prefix)

    monkeypatch.setattr(env.blobs, "delete_prefix", flaky)
    assert (await env.c.delete(f"/v1/sessions/{sid}", headers=env.h)).status_code == 503
    assert (await env.c.delete(f"/v1/sessions/{sid}", headers=env.h)).status_code == 204
    env.drain()
    assert len(deleted_lines(caplog)) == 1
    assert (await env.c.delete(f"/v1/sessions/{sid}", headers=env.h)).status_code == 404


async def test_stuck_cleanup_survives_both_attempts_failing_without_leaking_slots(env, monkeypatch):
    sid = await env.finished()
    monkeypatch.setattr(
        env.blobs, "delete_prefix", lambda p: (_ for _ in ()).throw(RuntimeError("down"))
    )
    assert (await env.c.delete(f"/v1/sessions/{sid}", headers=env.h)).status_code == 503
    env.drain()  # 2 attempts, both fail, 2xx on the last: nothing raised
    assert env.repo.get_session(env.uid, sid).state == "deleting"  # still there to retry


def count_releases(env: Env) -> list:
    calls: list = []
    orig = env.repo.release_run

    def release_run(uid, date, refund):
        calls.append(refund)
        orig(uid, date, refund)

    env.repo.release_run = release_run
    return calls


async def test_delete_with_a_queued_run_releases_its_slot_once_and_refunds(env):
    calls = count_releases(env)
    sid = await env.start()  # first run reserved + enqueued, not delivered
    assert env.counters() == (1, 1)
    assert (await env.c.delete(f"/v1/sessions/{sid}", headers=env.h)).status_code == 204
    assert calls == [True]  # never reached the LLM: refunded
    assert env.counters() == (0, 0)
    env.drain()  # the run task finds nothing and must not release again
    assert calls == [True] and env.counters() == (0, 0)
    assert remaining_docs(env, sid) == []


async def test_delete_mid_run_releases_once_and_usage_counters_stay(env):
    calls = count_releases(env)
    holder: dict = {}

    class DeletesItself(FakeEvaluation):
        async def run(self, *a, **kw):
            # the user deletes while the evaluation is in flight (the write-after-delete race
            # is deferred; only the cap slot is accounted for)
            delete_session_data(env.repo, env.blobs, env.uid, holder["sid"])
            return await super().run(*a, **kw)

    swap_eval(env, DeletesItself())
    sid = holder["sid"] = await env.start()
    env.drain()
    assert sid
    assert calls == [False]  # released by the delete (run was running: spent), not again
    assert env.counters() == (0, 1)  # usage count kept: it is per user, not per session


async def test_delete_mid_run_leaves_no_blobs_or_docs_behind(env):
    """The run finishes after the DELETE: its artifacts/report must not reappear (privacy)."""
    holder: dict = {}

    class DeletesItself(FakeEvaluation):
        async def run(self, *a, **kw):
            out = await super().run(*a, **kw)  # all progress callbacks are done
            delete_session_data(env.repo, env.blobs, env.uid, holder["sid"])  # DELETE lands now
            return out

    swap_eval(env, DeletesItself())
    sid = holder["sid"] = await env.start()
    env.drain()
    assert session_blob_keys(env, sid) == []
    assert remaining_docs(env, sid) == []
