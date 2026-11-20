import os
import socket
import subprocess
import sys
import time

import httpx
import pytest

pytestmark = pytest.mark.integration


def test_combined_mode_serves_healthz():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    env = {
        **os.environ,
        "ENV": "local",
        "SERVICE_MODE": "combined",
        "AUTH_MODE": "fake",
        "GIT_SHA": "itest",
    }
    proc = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "--factory",
            "onolys_api.app:create_app",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
        ],
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        deadline = time.time() + 20
        while True:
            try:
                r = httpx.get(f"http://127.0.0.1:{port}/v1/healthz", timeout=2)
                break
            except httpx.TransportError:
                assert time.time() < deadline and proc.poll() is None, "server did not start"
                time.sleep(0.2)
        assert r.status_code == 200
        assert r.json() == {"status": "ok", "service_mode": "combined", "code_version": "itest"}
        assert httpx.get(f"http://127.0.0.1:{port}/v1/openapi.json").status_code == 200
    finally:
        proc.terminate()
        proc.wait(10)
