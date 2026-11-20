"""Task 14: PHI-free structured logs, request logging, one `status=failed` line (PRD R10, AC9)."""

import hashlib
import hmac
import json
import logging

import test_run
import test_worker
from onolys_core.safe_log import ALLOWED_FIELDS
from test_run import CARD
from test_worker import SID, payload, runner_with

from onolys_api import logs
from onolys_api.adapters import FakeEvaluation
from onolys_api.config import Settings
from onolys_api.jobs.queue import TaskPayload
from onolys_api.jobs.worker import PermanentError, RetryableError

env = test_run.env
repo = test_worker.repo
CLIENT_LOGGERS = {"httpx", "httpcore", "asyncio"}
REQUIRED_FAILED = {"session_id", "run_id", "step", "error_code", "exc_class", "request_id"}


def lines(caplog) -> list[dict]:
    out = []
    for r in caplog.records:
        if r.name.startswith("onolys_api"):
            try:
                out.append(json.loads(r.getMessage()))
            except ValueError:
                out.append({"_unstructured": r.getMessage()})
    return out


def server_text(caplog) -> str:
    """Server-side lines only: httpx/asyncio lines are the test client's own."""
    return "\n".join(
        r.getMessage() for r in caplog.records if r.name.split(".")[0] not in CLIENT_LOGGERS
    )


def failed(caplog) -> list[dict]:
    return [d for d in lines(caplog) if d.get("status") == "failed"]


def test_api_fields_registered():
    want = {"uid_hash", "session_id", "run_id", "step", "status", "attempt", "duration_ms",
            "auth_kind", "error_code", "exc_class", "request_id", "code_version"}  # fmt: skip
    assert want <= ALLOWED_FIELDS


def test_emit_drops_unknown_and_text_fields_and_adds_code_version(caplog):
    logs.configure(Settings(git_sha="sha9", uid_hmac_key="k"))
    with caplog.at_level(logging.INFO):
        logs.emit("probe", session_id="s1", transcript="SECRET", surprise="SECRET2", status="ok")
    (d,) = lines(caplog)
    assert d["event"] == "probe" and d["session_id"] == "s1" and d["code_version"] == "sha9"
    assert d["message"] == "probe" and d["severity"] == "INFO"
    assert "SECRET" not in caplog.text and "surprise" not in d


def test_uid_hash_is_keyed_hmac_sha256_prefix():
    logs.configure(Settings(uid_hmac_key="key-1"))
    h1 = logs.uid_hash("alice")
    assert h1 == hmac.new(b"key-1", b"alice", hashlib.sha256).hexdigest()[:16]
    logs.configure(Settings(uid_hmac_key="key-2"))
    assert logs.uid_hash("alice") != h1


def test_settings_reads_uid_hmac_key_env():
    assert Settings.from_env({"UID_HMAC_KEY": "abc"}).uid_hmac_key == "abc"


# ---- request logging middleware ----


async def test_request_line_has_method_route_template_status_latency(env, caplog):
    sid = await env.new_session("t")
    caplog.clear()
    with caplog.at_level(logging.INFO):
        r = await env.c.get(f"/v1/sessions/{sid}", headers={**env.h, "X-Request-ID": "req-1"})
    assert r.status_code == 200
    (req,) = [d for d in lines(caplog) if d.get("event") == "request"]
    assert (req["method"], req["route"], req["status"]) == ("GET", "/v1/sessions/{id}", 200)
    assert isinstance(req["duration_ms"], int | float) and req["request_id"] == "req-1"
    assert req["auth_kind"] == "token"
    assert sid not in server_text(caplog) and env.uid not in server_text(
        caplog
    )  # no ids from the path


async def test_request_line_for_unmatched_route_has_no_path_or_query(env, caplog):
    with caplog.at_level(logging.INFO):
        r = await env.c.get("/v1/nope/SECRET-PATH?token=SECRET-Q", headers=env.h)
    assert r.status_code == 404
    (req,) = [d for d in lines(caplog) if d.get("event") == "request"]
    assert req["status"] == 404 and req["route"] == "unmatched"
    assert "SECRET" not in server_text(caplog)


# ---- failure lines ----


def test_failed_step_writes_exactly_one_line_with_required_keys(repo, caplog):

    def boom(ctx):
        raise PermanentError("invalid_audio")

    runner = runner_with(repo, boom)
    p = TaskPayload(kind="validate", uid=test_worker.UID, sid=SID, request_id="rid-step")
    with caplog.at_level(logging.INFO):
        runner.handle(p)
        runner.handle(p)  # duplicate delivery: no second line
    (f,) = failed(caplog)
    assert {"session_id", "step", "error_code", "exc_class", "request_id"} <= set(f)
    assert (f["session_id"], f["step"], f["error_code"], f["request_id"]) == (
        SID, "validate", "invalid_audio", "rid-step",
    )  # fmt: skip
    assert f["exc_class"] == "PermanentError" and f["severity"] == "ERROR"


def test_retry_is_not_failed_until_last_attempt(repo, caplog):

    def flaky(ctx):
        raise RetryableError("upstream_unavailable")

    runner = runner_with(repo, flaky)
    p = payload()
    with caplog.at_level(logging.INFO):
        assert runner.handle(p, 0).status_code == 503
        assert failed(caplog) == []
        assert runner.handle(p, 1).status_code == 200
    assert len(failed(caplog)) == 1


def test_unexpected_exception_logs_class_name_only(repo, caplog):

    def boom(ctx):
        raise KeyError("SENTINEL-EXC-MESSAGE")

    runner = runner_with(repo, boom)
    with caplog.at_level(logging.DEBUG):
        runner.handle(payload())
    (f,) = failed(caplog)
    assert f["exc_class"] == "KeyError" and f["error_code"] == "internal_error"
    assert "SENTINEL-EXC-MESSAGE" not in caplog.text


class ExplodingEval(FakeEvaluation):
    async def run(self, *a, **kw):
        raise ValueError("SENTINEL-EVAL-MESSAGE")


async def test_failed_run_writes_one_line_with_all_required_keys(env, caplog):
    test_run.swap_eval(env, ExplodingEval())
    sid = await env.start(rate=False)
    env.drain()  # the first run fails
    caplog.clear()
    with caplog.at_level(logging.INFO):
        r = await env.c.post(
            f"/v1/sessions/{sid}/runs", json={}, headers={**env.h, "X-Request-ID": "rid-run"}
        )
        assert r.status_code == 202
        run_id = r.json()["run_id"]
        env.drain()
    (f,) = failed(caplog)
    assert REQUIRED_FAILED <= set(f)
    assert (f["session_id"], f["run_id"], f["step"]) == (sid, run_id, "run")
    assert (f["error_code"], f["exc_class"], f["request_id"]) == (
        "internal_error", "ValueError", "rid-run",
    )  # fmt: skip
    assert "SENTINEL-EVAL-MESSAGE" not in caplog.text


async def test_run_enqueue_failure_is_one_failed_line(env, caplog):
    sid = await env.finished()

    class Down:
        def enqueue(self, payload, delay_s=0.0):
            raise ConnectionError("SENTINEL-QUEUE")

    env.app.state.queue = Down()
    caplog.clear()
    with caplog.at_level(logging.INFO):
        r = await env.c.post(
            f"/v1/sessions/{sid}/runs", json={}, headers={**env.h, "X-Request-ID": "rid-q"}
        )
    assert r.status_code == 503
    (f,) = failed(caplog)
    assert REQUIRED_FAILED <= set(f)
    assert (f["exc_class"], f["error_code"], f["request_id"]) == (
        "ConnectionError", "upstream_unavailable", "rid-q",
    )  # fmt: skip
    assert "SENTINEL-QUEUE" not in caplog.text


# ---- sentinel test over the full stub flow ----


async def test_no_sentinel_in_logs_over_full_flow(env, caplog, capsys, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-SENTINEL-LLM-KEY")
    caplog.set_level(logging.DEBUG)
    sentinels = ["SENTINEL-TITLE", "SENTINEL-NOTES", "sk-ant-SENTINEL-LLM-KEY"]
    sid = await env.new_session("SENTINEL-TITLE")
    await env.c.post(
        f"/v1/sessions/{sid}/speakers/confirm", json={"clinician_speaker": "S1"}, headers=env.h
    )
    card = {**CARD, "notes": "SENTINEL-NOTES"}
    await env.c.put(f"/v1/sessions/{sid}/rating", json={"final": True, "card": card}, headers=env.h)
    env.drain()
    tr = (await env.c.get(f"/v1/sessions/{sid}/transcript", headers=env.h)).json()
    texts = [t["text"] for t in tr["turns"] if len(t["text"]) > 12]
    assert texts
    key = (await env.c.post("/v1/api-key", headers=env.h)).json()["api_key"]
    r = await env.c.get("/v1/sessions", headers={"X-API-Key": key})
    assert r.status_code == 200
    await env.c.get(f"/v1/sessions/{sid}/reports/1", headers=env.h)
    token = env.h["Authorization"].split(" ", 1)[1]
    await env.c.delete(f"/v1/sessions/{sid}", headers=env.h)
    env.drain()

    out = server_text(caplog) + capsys.readouterr().err
    assert lines(caplog), "the flow produced no structured lines"
    for s in [*sentinels, *texts, key, token, env.uid, "Bearer"]:
        assert s not in out, s
    assert not [d for d in lines(caplog) if "_unstructured" in d], "unstructured API log line"
    assert failed(caplog) == []
