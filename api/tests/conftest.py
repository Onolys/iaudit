import json
from pathlib import Path

import httpx
import pytest

from onolys_api.app import create_app
from onolys_api.config import Settings

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
def app(settings):
    return create_app(settings)


@pytest.fixture
async def client(app):
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app, raise_app_exceptions=False), base_url="http://t"
    ) as c:
        yield c
