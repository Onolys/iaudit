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
