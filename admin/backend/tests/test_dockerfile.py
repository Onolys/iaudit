"""The deployed service sets ROUTES_FILE=config/<env>/routes.yaml (infra services.tf), resolved
against the image WORKDIR (/app). paudit's live client fails with ConfigError (HTTP 500) if the
image does not ship config/, as found on staging (SP07 task 11)."""

import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

ROOT = Path(__file__).resolve().parents[3]
DOCKERFILE = (ROOT / "admin" / "backend" / "Dockerfile").read_text()


def test_image_ships_routes_config_under_workdir():
    assert re.search(r"^COPY\s+config\s+/app/config\s*$", DOCKERFILE, re.M)
    assert re.search(r"^WORKDIR\s+/app\s*$", DOCKERFILE, re.M)


def test_dockerignore_does_not_exclude_config():
    lines = [ln.strip() for ln in (ROOT / ".dockerignore").read_text().splitlines()]
    assert "config" not in lines and "**/config" not in lines


@pytest.mark.parametrize("env", ["staging", "prod"])
def test_routes_file_exists_for_each_env(env):
    assert (ROOT / "config" / env / "routes.yaml").is_file()
