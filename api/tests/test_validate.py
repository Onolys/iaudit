"""The `validate` step (R3, AC5): each rejection code and warning, success layout. ffprobe and
ffmpeg are stubbed; fixtures are tiny generated files."""

import pytest
from audio_helpers import MAGIC, A, StubTools, tiny_wav

from onolys_api.app import create_app
from onolys_api.audio import ProbeResult
from onolys_api.repo.fake import FakeRepo
from onolys_api.storage.base import MAX_UPLOAD_BYTES

pytestmark = pytest.mark.unit
OK = ProbeResult(duration_s=15 * 60.0, audio_streams=1, video_streams=0)


@pytest.fixture
def repo(blobs):
    return FakeRepo(blobs)


async def run_validate(settings, repo, blobs, data: bytes, tools, ct="audio/wav", size=None):
    """Create a session, stage `data`, complete, drain the queue; return (app, sid)."""
    import httpx

    app = create_app(settings, repo=repo, blobs=blobs, audio_tools=tools)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app, raise_app_exceptions=False), base_url="http://t"
    ) as c:
        sid = (await c.post("/v1/sessions", json={}, headers=A)).json()["session"]["id"]
        up = (
            await c.post(
                f"/v1/sessions/{sid}/audio",
                json={"content_type": ct, "size_bytes": size or len(data)},
                headers=A,
            )
        ).json()
        blobs.put_bytes(f"uploads/alice/{sid}/{up['upload_id']}", data)
        assert (await c.post(f"/v1/sessions/{sid}/audio/complete", headers=A)).status_code == 202
    app.state.runner._registry.pop("transcribe")  # these tests stop at the hand-off to transcribe
    app.state.queue.drain()
    return app, sid


def assert_failed(repo, blobs, sid, code):
    s = repo.get_session("alice", sid)
    assert s.state == "failed" and s.error.code == code and s.error.step == "validate"
    assert repo.get_status("alice", sid).error_code == code
    assert s.steps["validate"].status == "failed"
    assert blobs.list_keys(f"uploads/alice/{sid}/") == []  # object removed
    assert blobs.list_keys(f"alice/{sid}/") == []


async def test_success_layout_recording_and_next_step(settings, repo, blobs):
    tools = StubTools(probe=OK)
    app, sid = await run_validate(settings, repo, blobs, tiny_wav(), tools)
    s = repo.get_session("alice", sid)
    assert s.state == "transcribing" and s.warnings == []
    assert s.steps["validate"].status == "done"
    assert blobs.list_keys(f"uploads/alice/{sid}/") == []  # staged object deleted
    assert blobs.list_keys(f"alice/{sid}/") == [
        f"alice/{sid}/audio/canonical.flac",
        f"alice/{sid}/audio/original.wav",
    ]
    assert blobs.get_bytes(f"alice/{sid}/audio/original.wav") == tiny_wav()
    (rec,) = repo.list_recordings("alice", sid)
    assert rec.gcs_uri == blobs.uri(f"alice/{sid}/audio/original.wav")
    assert (rec.format, rec.size, rec.duration_ms) == ("wav", len(tiny_wav()), 900_000)
    assert len(rec.sha256) == 64
    assert tools.transcoded == [("in.bin", None)]
    assert f"{sid}-transcribe" in app.state.queue.seen  # enqueued (T8 registers its handler)


@pytest.mark.parametrize("fmt", ["mp3", "wav", "m4a", "webm", "ogg"])
async def test_each_allowed_format_is_kept_as_original_ext(settings, repo, blobs, fmt):
    _, sid = await run_validate(settings, repo, blobs, MAGIC[fmt], StubTools(probe=OK))
    assert blobs.exists(f"alice/{sid}/audio/original.{fmt}")
    assert repo.get_session("alice", sid).state == "transcribing"


async def test_too_large_by_object_size(settings, repo, blobs, monkeypatch):
    monkeypatch.setattr(blobs, "size", lambda key: MAX_UPLOAD_BYTES + 1)
    tools = StubTools(probe=OK)
    _, sid = await run_validate(settings, repo, blobs, MAGIC["wav"], tools)
    assert_failed(repo, blobs, sid, "audio_too_large")
    assert tools.probed == []  # rejected before any work


async def test_bad_magic_bytes_unsupported_audio(settings, repo, blobs):
    tools = StubTools(probe=OK)
    _, sid = await run_validate(settings, repo, blobs, b"%PDF-1.7 not audio at all......", tools)
    assert_failed(repo, blobs, sid, "unsupported_audio")
    assert tools.probed == []


async def test_video_track_unsupported_audio(settings, repo, blobs):
    tools = StubTools(probe=ProbeResult(duration_s=60.0, audio_streams=1, video_streams=1))
    _, sid = await run_validate(settings, repo, blobs, MAGIC["m4a"], tools, ct="audio/mp4")
    assert_failed(repo, blobs, sid, "unsupported_audio")


async def test_no_audio_stream_audio_unreadable(settings, repo, blobs):
    tools = StubTools(probe=ProbeResult(duration_s=60.0, audio_streams=0, video_streams=0))
    _, sid = await run_validate(settings, repo, blobs, MAGIC["wav"], tools)
    assert_failed(repo, blobs, sid, "audio_unreadable")


async def test_ffprobe_failure_audio_unreadable(settings, repo, blobs):
    _, sid = await run_validate(settings, repo, blobs, MAGIC["wav"], StubTools(probe_error=True))
    assert_failed(repo, blobs, sid, "audio_unreadable")


@pytest.mark.parametrize(
    ("seconds", "ok"), [(0.99, False), (1.0, True), (25 * 60.0, True), (25 * 60 + 0.5, False)]
)
async def test_duration_bounds(settings, repo, blobs, seconds, ok):
    tools = StubTools(probe=ProbeResult(duration_s=seconds, audio_streams=1))
    _, sid = await run_validate(settings, repo, blobs, MAGIC["wav"], tools)
    if ok:
        assert repo.get_session("alice", sid).state == "transcribing"
    else:
        code = "audio_unreadable" if seconds < 1 else "audio_too_long"
        assert_failed(repo, blobs, sid, code)


async def test_short_recording_warning_only(settings, repo, blobs):
    tools = StubTools(probe=ProbeResult(duration_s=9 * 60.0, audio_streams=1))
    _, sid = await run_validate(settings, repo, blobs, MAGIC["wav"], tools)
    s = repo.get_session("alice", sid)
    assert s.state == "transcribing" and s.warnings == ["short_recording"]


async def test_ten_minutes_is_not_short(settings, repo, blobs):
    tools = StubTools(probe=ProbeResult(duration_s=600.0, audio_streams=1))
    _, sid = await run_validate(settings, repo, blobs, MAGIC["wav"], tools)
    assert repo.get_session("alice", sid).warnings == []


async def test_transcode_failure_audio_unreadable_and_objects_removed(settings, repo, blobs):
    _, sid = await run_validate(
        settings, repo, blobs, MAGIC["wav"], StubTools(probe=OK, transcode_error=True)
    )
    assert_failed(repo, blobs, sid, "audio_unreadable")


async def test_unknown_duration_is_bounded_then_measured_on_the_flac(settings, repo, blobs):
    """MediaRecorder WebM has no duration header: transcode with a cap, then probe the FLAC."""
    tools = StubTools(
        probe=ProbeResult(duration_s=None, audio_streams=1),
        flac_probe=ProbeResult(duration_s=300.0, audio_streams=1),
    )
    _, sid = await run_validate(settings, repo, blobs, MAGIC["webm"], tools, ct="audio/webm")
    s = repo.get_session("alice", sid)
    assert s.warnings == ["short_recording"] and s.state == "transcribing"
    assert tools.transcoded[0][1] is not None and tools.transcoded[0][1] > 25 * 60
    assert repo.list_recordings("alice", sid)[0].duration_ms == 300_000


async def test_unknown_duration_too_long_after_cap(settings, repo, blobs):
    tools = StubTools(
        probe=ProbeResult(duration_s=None, audio_streams=1),
        flac_probe=ProbeResult(duration_s=25 * 60 + 5.0, audio_streams=1),
    )
    _, sid = await run_validate(settings, repo, blobs, MAGIC["webm"], tools, ct="audio/webm")
    assert_failed(repo, blobs, sid, "audio_too_long")


async def test_redelivery_after_move_resumes_from_original(settings, repo, blobs):
    """A retry finds the staged object gone but the original in place: no failure."""
    app, sid = await run_validate(settings, repo, blobs, MAGIC["wav"], StubTools(probe=OK))
    # simulate a crash before the step was marked done: reset step + state, drop the canonical
    repo.update_session("alice", sid, {"steps.validate.status": "pending", "state": "validating"})
    blobs.delete(f"alice/{sid}/audio/canonical.flac")
    from onolys_api.jobs.queue import TaskPayload

    res = app.state.runner.handle(TaskPayload(kind="validate", uid="alice", sid=sid))
    assert res.status_code == 200
    assert blobs.exists(f"alice/{sid}/audio/canonical.flac")
    assert blobs.exists(f"alice/{sid}/audio/original.wav")


async def test_missing_object_audio_unreadable(settings, repo, blobs):
    app, sid = await run_validate(settings, repo, blobs, MAGIC["wav"], StubTools(probe=OK))
    # a second session whose staged object vanished before validate ran
    import httpx

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        sid2 = (await c.post("/v1/sessions", json={}, headers=A)).json()["session"]["id"]
        up = (
            await c.post(
                f"/v1/sessions/{sid2}/audio",
                json={"content_type": "audio/wav", "size_bytes": 5},
                headers=A,
            )
        ).json()
        blobs.put_bytes(f"uploads/alice/{sid2}/{up['upload_id']}", MAGIC["wav"])
        await c.post(f"/v1/sessions/{sid2}/audio/complete", headers=A)
        blobs.delete(f"uploads/alice/{sid2}/{up['upload_id']}")
    app.state.queue.drain()
    assert_failed(repo, blobs, sid2, "audio_unreadable")
