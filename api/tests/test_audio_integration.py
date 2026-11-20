"""One integration test with real ffmpeg/ffprobe: the canonical FLAC is FLAC / 16 kHz / mono and
the fake `Stt` receives an `AudioRef` to it (AC5)."""

import json
import shutil
import subprocess

import httpx
import pytest
from audio_helpers import A
from onolys_core.stt import SttParams

from onolys_api.adapters import FakeStt
from onolys_api.app import create_app
from onolys_api.audio import canonical_audio_ref
from onolys_api.repo.fake import FakeRepo

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not (shutil.which("ffmpeg") and shutil.which("ffprobe")), reason="ffmpeg/ffprobe missing"
    ),
]


def make_m4a(path):
    """2 s of a 44.1 kHz stereo tone as AAC in an MP4 container (a browser-style upload)."""
    subprocess.run(
        ["ffmpeg", "-nostdin", "-v", "error", "-f", "lavfi", "-i", "sine=frequency=440:duration=2",
         "-ac", "2", "-ar", "44100", "-c:a", "aac", str(path)],
        check=True,
    )  # fmt: skip


async def test_real_ffmpeg_transcode_to_16k_mono_flac_and_stt_gets_audioref(
    settings, blobs, tmp_path
):
    src = tmp_path / "in.m4a"
    make_m4a(src)
    repo = FakeRepo(blobs)
    app = create_app(settings, repo=repo, blobs=blobs)  # default tools = real ffmpeg
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        sid = (await c.post("/v1/sessions", json={}, headers=A)).json()["session"]["id"]
        up = (
            await c.post(
                f"/v1/sessions/{sid}/audio",
                json={"content_type": "audio/x-m4a", "size_bytes": src.stat().st_size},
                headers=A,
            )
        ).json()
        put = await c.put(
            up["upload_url"].removeprefix("http://localhost:8000"),
            content=src.read_bytes(),
            headers=up["required_headers"],
        )
        assert put.status_code == 200
        assert (await c.post(f"/v1/sessions/{sid}/audio/complete", headers=A)).status_code == 202
    app.state.queue.drain()

    s = repo.get_session("alice", sid)
    assert s.state == "transcribing", s.error
    assert blobs.exists(f"alice/{sid}/audio/original.m4a")
    assert blobs.list_keys(f"uploads/alice/{sid}/") == []

    flac = blobs.root / f"alice/{sid}/audio/canonical.flac"
    probe = json.loads(
        subprocess.run(
            ["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(flac)],
            check=True, capture_output=True, text=True,
        ).stdout
    )  # fmt: skip
    (stream,) = probe["streams"]
    assert (stream["codec_name"], stream["sample_rate"], stream["channels"]) == ("flac", "16000", 1)
    assert 1.5 < float(probe["format"]["duration"]) < 2.5

    (rec,) = repo.list_recordings("alice", sid)
    ref = canonical_audio_ref(blobs, "alice", sid, rec)
    assert ref.uri == blobs.uri(f"alice/{sid}/audio/canonical.flac")
    assert ref.mime == "audio/flac" and ref.duration_ms == rec.duration_ms
    assert ref.local_path_fn is not None and ref.local_path_fn().read_bytes()[:4] == b"fLaC"

    stt = FakeStt()
    handle = await stt.start(ref, SttParams(provider="fake", model="fake"))
    assert handle and stt.started[0][0].uri == ref.uri
