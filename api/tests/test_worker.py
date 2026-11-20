"""R5 / D3 / AC6 / AC12: queue, handler wrapper (retry, idempotency), worker route + OIDC."""

import time
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock

import httpx
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from google.api_core.exceptions import AlreadyExists
from google.auth import crypt, jwt
from onolys_core.errors import ConfigError

from onolys_api.app import create_app
from onolys_api.auth.oidc import OidcVerifier
from onolys_api.config import Settings
from onolys_api.jobs.queue import (
    CloudTasksQueue,
    InMemoryQueue,
    TaskPayload,
    task_name,
)
from onolys_api.jobs.worker import (
    HandlerSpec,
    PermanentError,
    RetryableError,
    TaskRunner,
)
from onolys_api.repo.fake import FakeRepo
from onolys_api.repo.models import RunDoc, SessionDoc, SessionStatusDoc

UID, SID, RUN = "u1", "s1", "r1"
WORKER_URL = "https://onolys-worker-staging-1.us-central1.run.app"
SA = "tasks-invoker-staging@onolys.iam.gserviceaccount.com"


@pytest.fixture
def repo(blobs):
    r = FakeRepo(blobs)
    now = datetime.now(UTC)
    r.create_session(
        UID, SID, SessionDoc(uid=UID, state="validating", created_at=now, updated_at=now),
        SessionStatusDoc(uid=UID, state="validating", updated_at=now),
    )  # fmt: skip
    r.create_run(UID, SID, RUN, RunDoc(uid=UID, session_id=SID, run_id=RUN))
    return r


def payload(kind="validate", **kw):
    return TaskPayload(kind=kind, uid=UID, sid=SID, request_id="req-1", **kw)


def runner_with(repo, fn, kind="validate", **spec_kw):
    runner = TaskRunner(repo, InMemoryQueue())
    spec_kw.setdefault("step", kind if kind != "run" else "run")
    spec_kw.setdefault("scope", "run" if kind == "run" else "step")
    runner.register(kind, HandlerSpec(fn, **spec_kw))
    return runner


# ---- names ----


def test_task_names():
    assert task_name(payload("validate")) == "s1-validate"
    assert task_name(payload("transcribe")) == "s1-transcribe"
    assert task_name(payload("transcribe-poll", n=3)) == "s1-poll-3"
    assert task_name(payload("run", run_id="r1")) == "r1-run"


# ---- retry semantics (AC6) ----


def test_transient_failure_succeeds_on_attempt_2(repo):
    calls = []

    def fn(ctx):
        calls.append(ctx.attempt)
        if ctx.attempt == 1:
            raise RetryableError("upstream_unavailable")

    runner = runner_with(repo, fn)
    r1 = runner.handle(payload(), retry_count=0)
    assert r1.status_code == 503  # Cloud Tasks retries
    assert repo.get_session(UID, SID).state == "validating"  # not failed yet
    r2 = runner.handle(payload(), retry_count=1)
    assert r2.status_code == 200 and calls == [1, 2]
    rec = repo.get_session(UID, SID).steps["validate"]
    assert rec.status == "done" and rec.attempts == 2


def test_two_failures_end_failed_no_third_attempt(repo):
    runner = runner_with(
        repo, lambda ctx: (_ for _ in ()).throw(RetryableError("upstream_unavailable"))
    )
    assert runner.handle(payload(), retry_count=0).status_code == 503
    last = runner.handle(payload(), retry_count=1)
    assert last.status_code == 200  # no 5xx on the last attempt: Cloud Tasks stops
    s = repo.get_session(UID, SID)
    assert (
        s.state == "failed"
        and s.error.code == "upstream_unavailable"
        and s.error.step == "validate"
    )
    assert s.steps["validate"].status == "failed"
    st = repo.get_status(UID, SID)
    assert st.state == "failed" and st.error_code == "upstream_unavailable"


def test_permanent_error_not_retried(repo):
    calls = []

    def fn(ctx):
        calls.append(1)
        raise PermanentError("invalid_audio")

    runner = runner_with(repo, fn)
    r = runner.handle(payload(), retry_count=0)
    assert r.status_code == 200 and calls == [1]
    assert repo.get_status(UID, SID).error_code == "invalid_audio"
    assert repo.get_session(UID, SID).state == "failed"


def test_unexpected_exception_is_permanent_internal_error(repo):
    def fn(ctx):
        raise ValueError("secret transcript text")

    r = runner_with(repo, fn).handle(payload(), retry_count=0)
    assert r.status_code == 200
    s = repo.get_session(UID, SID)
    assert s.error.code == "internal_error" and "secret" not in s.model_dump_json()


def test_timeout_is_retryable(repo):
    def fn(ctx):
        raise TimeoutError

    r = runner_with(repo, fn).handle(payload(), retry_count=0)
    assert r.status_code == 503


def test_duplicate_delivery_one_result(repo):
    calls = []
    runner = runner_with(repo, lambda ctx: calls.append(1))
    assert runner.handle(payload(), retry_count=0).status_code == 200
    again = runner.handle(payload(), retry_count=0)
    assert again.status_code == 200 and again.outcome == "duplicate" and calls == [1]


def test_concurrent_delivery_busy_then_lease_expiry_reclaims(repo):
    calls = []
    runner = runner_with(repo, lambda ctx: calls.append(1))
    assert repo.claim_step(UID, SID, "validate", datetime.now(UTC), 540).outcome == "claimed"
    busy = runner.handle(payload(), retry_count=0)
    assert busy.status_code == 503 and busy.outcome == "busy" and calls == []
    assert runner.handle(payload(), retry_count=1).status_code == 200  # last attempt: no 5xx
    later = datetime.now(UTC) + timedelta(seconds=541)
    runner2 = TaskRunner(repo, InMemoryQueue(), clock=lambda: later)
    runner2.register("validate", HandlerSpec(lambda ctx: calls.append(2), step="validate"))
    assert runner2.handle(payload(), retry_count=0).status_code == 200 and calls == [2]


def test_run_scope_claims_run_record_and_fails_session(repo):
    repo.update_session(UID, SID, {"state": "running"}, status={"state": "running"})
    calls = []

    def fn(ctx):
        calls.append(ctx.attempt)
        raise PermanentError("evaluation_failed")

    runner = runner_with(repo, fn, kind="run")
    assert runner.handle(payload("run", run_id=RUN), retry_count=0).status_code == 200
    assert repo.get_run(UID, SID, RUN).status == "failed"
    assert repo.get_run(UID, SID, RUN).error == "evaluation_failed"
    assert repo.get_status(UID, SID).error_code == "evaluation_failed"
    assert runner.handle(payload("run", run_id=RUN), retry_count=0).outcome == "duplicate"
    assert calls == [1]


def test_run_success_marks_done(repo):
    runner = runner_with(repo, lambda ctx: None, kind="run")
    runner.handle(payload("run", run_id=RUN), retry_count=0)
    r = repo.get_run(UID, SID, RUN)
    assert r.status == "done" and r.ended is not None


def test_handler_gets_deadline_request_id_and_can_enqueue(repo):
    seen = {}

    def fn(ctx):
        seen.update(rid=ctx.request_id, left=ctx.remaining_s())
        ctx.enqueue(TaskPayload(kind="transcribe", uid=UID, sid=SID))

    runner = runner_with(repo, fn)
    runner.handle(payload(), retry_count=0)
    assert seen["rid"] == "req-1" and 470 < seen["left"] <= 480
    queued = runner.queue.pending[0]
    assert queued.request_id == "req-1"  # propagated into follow-up tasks


def test_expired_deadline_is_retryable(repo):
    def fn(ctx):
        ctx.check_deadline()

    runner = runner_with(repo, fn)
    runner._deadline_s = -1
    assert runner.handle(payload(), retry_count=0).status_code == 503


def test_no_claim_handler_failure_still_fails_step(repo):
    def fn(ctx):
        raise PermanentError("transcription_failed")

    runner = runner_with(repo, fn, kind="transcribe-poll", step="transcribe", claim=False)
    r = runner.handle(payload("transcribe-poll", n=1), retry_count=0)
    assert r.status_code == 200
    assert repo.get_status(UID, SID).error_code == "transcription_failed"


def test_deleted_session_is_acked(repo):
    repo.delete_session(UID, SID)
    r = runner_with(repo, lambda ctx: None).handle(payload(), retry_count=0)
    assert r.status_code == 200 and r.outcome == "gone"


# ---- queues ----


def test_in_memory_queue_dedups_names_and_drain_emulates_cloud_retry(repo):
    calls = []

    def fn(ctx):
        calls.append(ctx.attempt)
        if ctx.attempt == 1:
            raise RetryableError("upstream_unavailable")

    runner = runner_with(repo, fn)
    q = runner.queue
    q.enqueue(payload())
    q.enqueue(payload())  # same name: dropped like Cloud Tasks does
    assert len(q.pending) == 1
    q.drain()
    assert calls == [1, 2] and repo.get_session(UID, SID).steps["validate"].status == "done"


def test_cloud_queue_builds_task_with_oidc_delay_and_request_id():
    client = MagicMock()
    client.queue_path.return_value = "projects/p/locations/l/queues/steps-staging"
    s = Settings(env="staging", gcp_project="p", region="l", tasks_queue="steps-staging",
                 tasks_sa=SA, worker_url=WORKER_URL, service_mode="worker", auth_mode="idp")  # fmt: skip
    q = CloudTasksQueue(s, client=client)
    q.enqueue(payload("transcribe-poll", n=2), delay_s=15)
    client.queue_path.assert_called_with("p", "l", "steps-staging")
    req = client.create_task.call_args.kwargs["request"]
    task = req["task"]
    assert req["parent"] == "projects/p/locations/l/queues/steps-staging"
    assert task["name"] == "projects/p/locations/l/queues/steps-staging/tasks/s1-poll-2"
    http = task["http_request"]
    assert http["url"] == f"{WORKER_URL}/tasks/transcribe-poll"
    assert http["oidc_token"] == {"service_account_email": SA, "audience": WORKER_URL}
    assert b'"request_id":"req-1"' in http["body"].replace(b" ", b"")
    assert task["schedule_time"] is not None
    assert task["dispatch_deadline"].seconds == 600


def test_cloud_queue_already_exists_is_dedup_success():
    client = MagicMock()
    client.create_task.side_effect = AlreadyExists("dup")
    s = Settings(env="staging", tasks_queue="q", tasks_sa=SA, worker_url=WORKER_URL,
                 service_mode="worker", auth_mode="idp")  # fmt: skip
    CloudTasksQueue(s, client=client).enqueue(payload())  # no raise


def test_cloud_queue_no_delay_has_no_schedule_time():
    client = MagicMock()
    s = Settings(env="staging", tasks_queue="q", tasks_sa=SA, worker_url=WORKER_URL,
                 service_mode="worker", auth_mode="idp")  # fmt: skip
    CloudTasksQueue(s, client=client).enqueue(payload())
    assert "schedule_time" not in client.create_task.call_args.kwargs["request"]["task"]


# ---- OIDC + route (AC12) ----

KID = "g1"


def _keypair():
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    priv = key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
    ).decode()
    pub = (
        key.public_key()
        .public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
        .decode()
    )
    return priv, pub


PRIV, PUB = _keypair()
OTHER_PRIV, _ = _keypair()


def mint(*, aud=WORKER_URL, email=SA, verified=True, iss="https://accounts.google.com",
         exp_in=3600, priv=PRIV):  # fmt: skip
    now = int(time.time())
    claims = {"aud": aud, "iss": iss, "email": email, "email_verified": verified,
              "sub": "123", "iat": now - 5, "exp": now + exp_in}  # fmt: skip
    return jwt.encode(crypt.RSASigner.from_string(priv, KID), claims, header={"kid": KID}).decode()


def verifier():
    return OidcVerifier(WORKER_URL, SA, fetch_certs=lambda: {KID: PUB})


@pytest.mark.parametrize(
    "kw",
    [
        {"aud": "https://other.run.app"},
        {"email": "someone@else.com"},
        {"verified": False},
        {"iss": "https://evil.example"},
        {"exp_in": -100},
        {"priv": OTHER_PRIV},
    ],
)
def test_oidc_verifier_rejects_bad_tokens(kw):
    from onolys_api.auth.idtoken import InvalidToken

    with pytest.raises(InvalidToken):
        verifier().verify(mint(**kw))


def test_oidc_verifier_accepts_good_token():
    assert verifier().verify(mint()) == SA


@pytest.fixture
def worker_settings():
    return Settings(env="staging", service_mode="worker", auth_mode="idp", adapters="stub",
                    tasks_queue="steps-staging", tasks_sa=SA, worker_url=WORKER_URL,
                    gcp_project="onolys", region="us-central1")  # fmt: skip


async def _post(app, kind="validate", body=None, headers=None):
    body = body or {"kind": kind, "uid": UID, "sid": SID, "request_id": "req-9"}
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app, raise_app_exceptions=False), base_url="http://t"
    ) as c:
        return await c.post(f"/tasks/{kind}", json=body, headers=headers or {})


@pytest.fixture
def worker_app(worker_settings, repo, blobs):
    app = create_app(worker_settings, repo=repo, blobs=blobs, oidc_verifier=verifier())
    app.state.runner.register("validate", HandlerSpec(lambda ctx: None, step="validate"))
    return app


async def test_worker_rejects_missing_or_bad_oidc(worker_app):
    assert (await _post(worker_app)).status_code == 401
    bad = {"Authorization": f"Bearer {mint(aud='https://x.run.app')}"}
    assert (await _post(worker_app, headers=bad)).status_code == 401
    assert (await _post(worker_app, headers={"Authorization": "Bearer junk"})).status_code == 401
    assert repo_untouched(worker_app)


def repo_untouched(app):
    return "validate" not in app.state.repo.get_session(UID, SID).steps


async def test_worker_accepts_valid_oidc_and_maps_retry_header(worker_app):
    good = {"Authorization": f"Bearer {mint()}"}
    r = await _post(worker_app, headers=good)
    assert r.status_code == 200
    assert worker_app.state.repo.get_session(UID, SID).steps["validate"].status == "done"


async def test_worker_route_returns_503_then_200_on_retry_header(worker_settings, repo, blobs):
    app = create_app(worker_settings, repo=repo, blobs=blobs, oidc_verifier=verifier())

    def fn(ctx):
        if ctx.attempt == 1:
            raise RetryableError("upstream_unavailable")

    app.state.runner.register("validate", HandlerSpec(fn, step="validate"))
    h = {"Authorization": f"Bearer {mint()}"}
    assert (await _post(app, headers=h)).status_code == 503
    assert (await _post(app, headers={**h, "X-CloudTasks-TaskRetryCount": "1"})).status_code == 200


async def test_worker_route_unknown_kind_404_and_hidden_from_schema(worker_app):
    h = {"Authorization": f"Bearer {mint()}"}
    assert (
        await _post(
            worker_app,
            kind="nope",
            body={"kind": "validate", "uid": UID, "sid": SID},
            headers=h,
        )
    ).status_code == 404
    assert not any(p.startswith("/tasks") for p in worker_app.openapi()["paths"])


@pytest.mark.parametrize("env", ["local", "test"])
async def test_oidc_bypassed_only_in_local_test(env, repo, blobs):
    s = Settings(env=env, service_mode="combined", auth_mode="fake")
    app = create_app(s, repo=repo, blobs=blobs)
    app.state.runner.register("validate", HandlerSpec(lambda ctx: None, step="validate"))
    assert (await _post(app)).status_code == 200


def test_worker_non_local_requires_worker_url_and_sa(worker_settings, repo, blobs):
    with pytest.raises(ConfigError):
        create_app(replace(worker_settings, worker_url=""), repo=repo, blobs=blobs)


def test_combined_queue_calls_runner_directly(repo, blobs):
    s = Settings(env="test", service_mode="combined", auth_mode="fake")
    app = create_app(s, repo=repo, blobs=blobs)
    calls = []
    app.state.runner.register("validate", HandlerSpec(lambda ctx: calls.append(1), step="validate"))
    app.state.queue.enqueue(payload())
    app.state.queue.drain()
    assert calls == [1]
