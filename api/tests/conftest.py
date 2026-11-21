import json
from pathlib import Path

import httpx
import pytest

from onolys_api.app import create_app
from onolys_api.config import Settings
from onolys_api.repo.fake import FakeRepo
from onolys_api.storage.fake import FakeBlobStore

SCHEMA = (
    Path(__file__).resolve().parents[2] / "docs/contracts/public/public-error-response.schema.json"
)


@pytest.fixture
def schema() -> dict:
    return json.loads(SCHEMA.read_text())


@pytest.fixture
def settings() -> Settings:
    return Settings(
        env="test",
        service_mode="combined",
        auth_mode="fake",
        git_sha="abc123",
        cors_origins=("https://app.onolys.com",),
    )


@pytest.fixture
def blobs(tmp_path):
    return FakeBlobStore(tmp_path / "blobs")


@pytest.fixture
def app(settings, blobs):
    return create_app(settings, repo=FakeRepo(blobs), blobs=blobs)


@pytest.fixture
async def client(app):
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app, raise_app_exceptions=False), base_url="http://t"
    ) as c:
        yield c


# Firestore-emulator transaction contention ("Aborted: 409 Transaction lock timeout") makes these
# firestore-backed params flaky. The in-memory ("fake") params are deterministic and stay blocking.
FLAKY_FIRESTORE_TESTS = {
    "test_concurrent_reservations_never_exceed_the_cap",
    "test_concurrent_attempts_cannot_exceed_the_active_run_limit",
    "test_two_concurrent_claims_one_wins",
}


@pytest.hookimpl(tryfirst=True)
def pytest_collection_modifyitems(items):
    for item in items:
        callspec = getattr(item, "callspec", None)
        if (
            item.originalname in FLAKY_FIRESTORE_TESTS
            and callspec is not None
            and callspec.params.get("repo") == "firestore"
        ):
            item.add_marker(pytest.mark.flaky)
