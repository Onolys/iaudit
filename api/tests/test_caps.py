"""Daily run cap + concurrent-run limit + GET /usage (R8, D14, AC7).

Repo-level tests run against FakeRepo and the Firestore emulator (when FIRESTORE_EMULATOR_HOST is
set); the API tests use FakeRepo.
"""

import os
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta

import httpx
import pytest

from onolys_api.app import create_app
from onolys_api.config import Settings
from onolys_api.errors import ApiError
from onolys_api.jobs import caps
from onolys_api.repo.fake import FakeRepo
from onolys_api.storage.fake import FakeBlobStore

HAS_EMULATOR = bool(os.environ.get("FIRESTORE_EMULATOR_HOST"))
DAY = "2026-11-20"
NOON = datetime(2026, 11, 20, 12, 0, tzinfo=UTC)


@pytest.fixture(params=["fake", pytest.param("firestore", marks=pytest.mark.integration)])
def repo(request, tmp_path):
    blobs = FakeBlobStore(tmp_path / "blobs", bucket="test-bucket")
    if request.param == "fake":
        return FakeRepo(blobs)
    if not HAS_EMULATOR:
        pytest.skip("FIRESTORE_EMULATOR_HOST not set")
    from google.auth.credentials import AnonymousCredentials
    from google.cloud import firestore

    from onolys_api.repo.firestore import FirestoreRepo

    client = firestore.Client(project="demo-onolys", credentials=AnonymousCredentials())
    return FirestoreRepo(client, blobs)


def uid() -> str:
    return f"u-{uuid.uuid4().hex[:10]}"


def settings(**kw) -> Settings:
    return Settings(env="test", auth_mode="fake", **kw)


def set_user_fields(repo, u: str, **fields) -> None:
    """Write fields onto users/{uid} (the per-user override) on either repo."""
    if isinstance(repo, FakeRepo):
        d = repo._get(f"users/{u}") or {}
        repo._put(f"users/{u}", {**d, **fields})
    else:
        repo._client.collection("users").document(u).set(fields, merge=True)


def code_of(exc: ApiError) -> str:
    return exc.details[0]["code"]


def test_21st_run_of_the_day_is_429_daily_cap_reached(repo):
    u, s = uid(), settings(daily_run_cap=20, max_active_runs=1000)
    for _ in range(20):
        caps.reserve_run(repo, s, u, NOON)
    with pytest.raises(ApiError) as e:
        caps.reserve_run(repo, s, u, NOON)
    assert e.value.status == 429 and code_of(e.value) == "daily_cap_reached"
    assert repo.get_usage(u, DAY).runs == 20  # the refused attempt is not counted


def test_new_utc_day_starts_a_fresh_count(repo):
    u, s = uid(), settings(daily_run_cap=1, max_active_runs=1000)
    caps.reserve_run(repo, s, u, NOON)
    with pytest.raises(ApiError):
        caps.reserve_run(repo, s, u, NOON)
    caps.reserve_run(repo, s, u, NOON + timedelta(days=1))


def test_per_user_override_beats_the_config_default(repo):
    u, s = uid(), settings(daily_run_cap=20, max_active_runs=1000)
    set_user_fields(repo, u, daily_cap=2)
    caps.reserve_run(repo, s, u, NOON)
    caps.reserve_run(repo, s, u, NOON)
    with pytest.raises(ApiError) as e:
        caps.reserve_run(repo, s, u, NOON)
    assert code_of(e.value) == "daily_cap_reached"


def test_concurrent_reservations_never_exceed_the_cap(repo):
    u, s = uid(), settings(daily_run_cap=3, max_active_runs=1000)

    def attempt(_):
        try:
            caps.reserve_run(repo, s, u, NOON)
            return "ok"
        except ApiError as e:
            return code_of(e)

    with ThreadPoolExecutor(6) as ex:
        outs = list(ex.map(attempt, range(6)))
    assert outs.count("ok") == 3 and outs.count("daily_cap_reached") == 3
    assert repo.get_usage(u, DAY).runs == 3


def test_refund_before_any_llm_call_frees_the_slot_and_the_count(repo):
    u, s = uid(), settings(daily_run_cap=1, max_active_runs=1000)
    day = caps.reserve_run(repo, s, u, NOON)
    assert day == DAY
    with pytest.raises(ApiError):
        caps.reserve_run(repo, s, u, NOON)
    caps.release_run(repo, u, day, refund=True)
    assert repo.get_usage(u, DAY).runs == 0
    caps.reserve_run(repo, s, u, NOON)  # the user can run again


def test_release_without_refund_keeps_the_daily_count(repo):
    u, s = uid(), settings(daily_run_cap=1, max_active_runs=1)
    day = caps.reserve_run(repo, s, u, NOON)
    caps.release_run(repo, u, day, refund=False)  # run finished after spending LLM calls
    assert repo.get_usage(u, DAY).runs == 1
    with pytest.raises(ApiError) as e:
        caps.reserve_run(repo, s, u, NOON)
    assert code_of(e.value) == "daily_cap_reached"


def test_release_never_goes_below_zero(repo):
    u = uid()
    caps.release_run(repo, u, DAY, refund=True)
    caps.release_run(repo, u, DAY, refund=True)
    assert repo.get_usage(u, DAY).runs == 0
    s = settings(daily_run_cap=5, max_active_runs=1)
    caps.reserve_run(repo, s, u, NOON)
    with pytest.raises(ApiError):  # the stray releases did not create extra slots
        caps.reserve_run(repo, s, u, NOON)


def test_third_concurrent_active_run_is_429_and_a_finished_run_frees_a_slot(repo):
    u, s = uid(), settings(daily_run_cap=20, max_active_runs=2)
    d1 = caps.reserve_run(repo, s, u, NOON)
    caps.reserve_run(repo, s, u, NOON)
    with pytest.raises(ApiError) as e:
        caps.reserve_run(repo, s, u, NOON)
    assert e.value.status == 429 and code_of(e.value) == "daily_cap_reached"
    assert repo.get_usage(u, DAY).runs == 2  # the refused attempt is not counted
    caps.release_run(repo, u, d1, refund=False)
    caps.reserve_run(repo, s, u, NOON)


def test_concurrent_attempts_cannot_exceed_the_active_run_limit(repo):
    u, s = uid(), settings(daily_run_cap=20, max_active_runs=2)

    def attempt(_):
        try:
            caps.reserve_run(repo, s, u, NOON)
            return "ok"
        except ApiError as e:
            return code_of(e)

    with ThreadPoolExecutor(6) as ex:
        outs = list(ex.map(attempt, range(6)))
    assert outs.count("ok") == 2 and outs.count("daily_cap_reached") == 4


def test_per_user_active_limit_override(repo):
    u, s = uid(), settings(daily_run_cap=20, max_active_runs=2)
    set_user_fields(repo, u, max_active_runs=1)
    caps.reserve_run(repo, s, u, NOON)
    with pytest.raises(ApiError):
        caps.reserve_run(repo, s, u, NOON)


def test_usage_view_and_reset_time(repo):
    u, s = uid(), settings(daily_run_cap=20)
    assert caps.usage_view(repo, s, u, NOON) == (0, 20, datetime(2026, 11, 21, tzinfo=UTC))
    caps.reserve_run(repo, s, u, NOON)
    set_user_fields(repo, u, daily_cap=7)
    assert caps.usage_view(repo, s, u, NOON) == (1, 7, datetime(2026, 11, 21, tzinfo=UTC))


def test_max_active_runs_setting(monkeypatch):
    assert Settings.from_env({}).max_active_runs == 2
    assert Settings.from_env({"MAX_ACTIVE_RUNS": "3"}).max_active_runs == 3


# ---- GET /v1/usage ----

A = {"Authorization": "Bearer test:alice"}


@pytest.fixture
def api_repo(tmp_path):
    return FakeRepo(FakeBlobStore(tmp_path / "b"))


@pytest.fixture
async def api(tmp_path, api_repo):
    app = create_app(
        Settings(env="test", auth_mode="fake", service_mode="combined", daily_run_cap=20),
        repo=api_repo,
        blobs=FakeBlobStore(tmp_path / "b2"),
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app, raise_app_exceptions=False), base_url="http://t"
    ) as c:
        yield c


async def test_get_usage_requires_auth(api):
    assert (await api.get("/v1/usage")).status_code == 401


async def test_get_usage_shape_and_counts(api, api_repo):
    r = await api.get("/v1/usage", headers=A)
    assert r.status_code == 200
    body = r.json()
    assert set(body) == {"runs_today", "daily_cap", "resets_at"}
    assert body["runs_today"] == 0 and body["daily_cap"] == 20
    resets = datetime.fromisoformat(body["resets_at"].replace("Z", "+00:00"))
    now = datetime.now(UTC)
    assert now < resets <= now + timedelta(days=1)
    assert (resets.hour, resets.minute, resets.second) == (0, 0, 0)
    api_repo.add_usage("alice", now.strftime("%Y-%m-%d"), runs=3)
    set_user_fields(api_repo, "alice", daily_cap=9)
    body = (await api.get("/v1/usage", headers=A)).json()
    assert body["runs_today"] == 3 and body["daily_cap"] == 9


async def test_get_usage_is_per_user(api, api_repo):
    api_repo.add_usage("bob", datetime.now(UTC).strftime("%Y-%m-%d"), runs=4)
    assert (await api.get("/v1/usage", headers=A)).json()["runs_today"] == 0
