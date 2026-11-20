"""AC17: the quickstart's curl sequence (extracted from the OpenAPI description) runs against a
real `SERVICE_MODE=combined` server with stub adapters."""

import json
import os
import re
import shutil
import socket
import subprocess
import sys
import time

import httpx
import pytest

from onolys_api import openapi

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not all(shutil.which(t) for t in ("ffmpeg", "curl", "jq", "bash")),
        reason="ffmpeg/curl/jq missing",
    ),
]


def quickstart_script() -> str:
    desc = json.loads(openapi.render())["info"]["description"]
    blocks = re.findall(r"```bash\n(.*?)```", desc, re.S)
    assert blocks, "no bash block in the description"
    return "\n".join(blocks)


def test_quickstart_runs_end_to_end(tmp_path):
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    base = f"http://127.0.0.1:{port}"
    env = {
        **os.environ,
        "ENV": "local",
        "SERVICE_MODE": "combined",
        "AUTH_MODE": "fake",
        "ADAPTERS": "stub",
        "FAKE_BLOB_DIR": str(tmp_path / "blobs"),
        "FAKE_BLOB_BASE_URL": base,
    }
    env.pop("FIRESTORE_EMULATOR_HOST", None)
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "--factory", "onolys_api.app:create_app",
         "--host", "127.0.0.1", "--port", str(port)],
        env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )  # fmt: skip
    try:
        deadline = time.time() + 20
        while True:
            try:
                httpx.get(f"{base}/v1/healthz", timeout=2)
                break
            except httpx.TransportError:
                assert time.time() < deadline and proc.poll() is None, "server did not start"
                time.sleep(0.2)
        audio = tmp_path / "session.m4a"
        subprocess.run(
            ["ffmpeg", "-nostdin", "-v", "error", "-f", "lavfi", "-i",
             "sine=frequency=440:duration=2", "-c:a", "aac", str(audio)],
            check=True,
        )  # fmt: skip
        out = subprocess.run(
            ["bash", "-c", quickstart_script()],
            env={**os.environ, "BASE": f"{base}/v1", "AUTH": "Authorization: Bearer test:alice",
                 "AUDIO": str(audio)},
            capture_output=True, text=True, timeout=120,
        )  # fmt: skip
        print(out.stdout)
        print(out.stderr)
        assert out.returncode == 0, out.stderr
        report = json.loads(out.stdout.strip().splitlines()[-1])
        assert report["version"] == 1 and report["report"]["scorecard"]
    finally:
        proc.terminate()
        proc.wait(10)
