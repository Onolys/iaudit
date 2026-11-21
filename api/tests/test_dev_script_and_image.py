"""AC12 / D6: the one-command local run (`api/scripts/dev.sh`) and the single image's contract
(Dockerfile + entrypoint) match what Cloud Run (SP06 services.tf) provides: PORT and
SERVICE_MODE api|worker|combined, ffmpeg, GIT_SHA build arg, vendored Redoc.
The image build itself is a CI/CD step; here we check the files and run the entrypoint."""

import json
import os
import re
import shutil
import socket
import stat
import subprocess
from pathlib import Path

import pytest

API = Path(__file__).resolve().parents[1]
REPO = API.parent
DEV = API / "scripts/dev.sh"
DOCKERFILE = API / "Dockerfile"
ENTRYPOINT = API / "docker-entrypoint.sh"
SERVICES_TF = REPO / "infra/modules/environment/services.tf"


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


needs_tools = pytest.mark.skipif(
    not all(shutil.which(t) for t in ("uv", "ffmpeg", "curl", "jq", "bash")),
    reason="uv/ffmpeg/curl/jq missing",
)


def test_dev_script_preflight_and_flags():
    assert DEV.stat().st_mode & stat.S_IXUSR
    env = {**os.environ, "PORT": str(free_port())}
    ok = subprocess.run([str(DEV), "--check"], env=env, capture_output=True, text=True)
    assert ok.returncode == 0 and "preflight ok" in ok.stdout
    bad = subprocess.run([str(DEV), "--nope"], env=env, capture_output=True, text=True)
    assert bad.returncode == 2
    with socket.socket() as s:  # a busy port is a clear preflight failure, not a hang
        s.bind(("127.0.0.1", 0))
        s.listen()
        busy = subprocess.run(
            [str(DEV), "--check"],
            env={**os.environ, "PORT": str(s.getsockname()[1])},
            capture_output=True,
            text=True,
        )
    assert busy.returncode == 1 and "in use" in busy.stderr


@pytest.mark.integration
@needs_tools
def test_dev_script_checks_and_runs_combined_quickstart():
    out = subprocess.run(
        [str(DEV), "--quickstart"],
        env={**os.environ, "PORT": str(free_port()), "UV_NO_SYNC": "1"},
        capture_output=True,
        text=True,
        timeout=180,
    )
    assert out.returncode == 0, out.stderr
    report = json.loads(out.stdout.strip().splitlines()[-1])
    assert report["version"] == 1 and report["report"]["scorecard"]


def test_dockerfile_matches_the_cloud_run_contract():
    df = DOCKERFILE.read_text()
    assert "ffmpeg" in df, "the validate step needs ffmpeg/ffprobe in the image"
    assert re.search(r"^ARG GIT_SHA", df, re.M) and "GIT_SHA=${GIT_SHA}" in df
    assert 'ENTRYPOINT ["docker-entrypoint.sh"]' in df and "USER onolys" in df
    assert "COPY api/src api/src" in df  # carries static/redoc.standalone.js (vendored Redoc)
    assert (API / "src/onolys_api/static/redoc.standalone.js").is_file()
    assert "uv sync --frozen" in df and "--package onolys-api" in df
    ignore = (REPO / ".dockerignore").read_text().split()
    assert {"**/.git", ".worktrees", "**/node_modules", "**/.venv"} <= set(ignore)
    assert ENTRYPOINT.stat().st_mode & stat.S_IXUSR


def test_service_modes_in_terraform_are_accepted_by_the_entrypoint():
    pattern = r'name\s*=\s*"SERVICE_MODE"\s*value\s*=\s*"(\w+)"'
    modes = set(re.findall(pattern, SERVICES_TF.read_text()))
    assert modes == {"api", "worker"}, modes
    script = ENTRYPOINT.read_text()
    assert all(m in script for m in (*modes, "combined"))


def run_entrypoint(tmp_path, **env):
    shim = tmp_path / "bin"
    shim.mkdir(exist_ok=True)
    uvicorn = shim / "uvicorn"
    uvicorn.write_text('#!/bin/sh\necho "mode=$SERVICE_MODE args=$*"\n')
    uvicorn.chmod(0o755)
    base = {k: v for k, v in os.environ.items() if k not in ("SERVICE_MODE", "PORT")}
    return subprocess.run(
        ["sh", str(ENTRYPOINT)],
        env={**base, "PATH": f"{shim}:{os.environ['PATH']}", **env},
        capture_output=True,
        text=True,
    )


@pytest.mark.parametrize("mode", ["api", "worker", "combined"])
def test_entrypoint_execs_uvicorn_on_port_with_each_mode(tmp_path, mode):
    r = run_entrypoint(tmp_path, SERVICE_MODE=mode, PORT="9123")
    assert r.returncode == 0, r.stderr
    assert f"mode={mode}" in r.stdout
    assert "--factory onolys_api.app:create_app" in r.stdout
    assert "--host 0.0.0.0 --port 9123" in r.stdout


def test_entrypoint_defaults_and_rejects_unknown_mode(tmp_path):
    r = run_entrypoint(tmp_path)
    assert r.returncode == 0 and "mode=api" in r.stdout and "--port 8080" in r.stdout
    bad = run_entrypoint(tmp_path, SERVICE_MODE="both")
    assert bad.returncode == 2 and "SERVICE_MODE" in bad.stderr
