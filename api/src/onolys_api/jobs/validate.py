"""The `validate` step (PRD R3, D5): bytes in safely, one canonical format out.

Checks in order: object size, magic bytes, ffprobe (audio stream, no video, 1 s to 25 min).
A passing upload moves to `{uid}/{sid}/audio/original.{ext}`, is transcoded to
`canonical.flac` (16 kHz mono), the staged object is deleted, the recording doc is written,
and `transcribe` is enqueued. A failure removes every object of the session's audio and
records the public code. Idempotent: a redelivery after the move resumes from the original.
Logs carry codes only, never file names or content.
"""

import hashlib
import tempfile
from pathlib import Path

from onolys_api.audio import (
    CANONICAL_TYPES,
    MAX_DURATION_S,
    MIN_DURATION_S,
    SHORT_RECORDING_S,
    UNKNOWN_DURATION_CAP_S,
    AudioTools,
    ToolError,
    canonical_key,
    original_key,
    sniff,
    staging_key,
)
from onolys_api.jobs.machine import advance
from onolys_api.jobs.queue import TaskPayload
from onolys_api.jobs.worker import Handler, PermanentError, TaskContext
from onolys_api.repo.models import RecordingDoc
from onolys_api.storage.base import MAX_UPLOAD_BYTES, BlobStore

SHORT_WARNING = "short_recording"


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def make_validate_handler(blobs: BlobStore, tools: AudioTools) -> Handler:
    def purge(uid: str, sid: str) -> None:
        blobs.delete_prefix(f"uploads/{uid}/{sid}/")
        blobs.delete_prefix(f"{uid}/{sid}/audio/")

    def fail(ctx: TaskContext, code: str) -> PermanentError:
        purge(ctx.uid, ctx.sid)
        return PermanentError(code)

    def find_source(ctx: TaskContext, upload_id: str | None) -> tuple[str, bool] | None:
        """(key, already_moved): the staged object, else an original left by an earlier attempt."""
        if upload_id:
            staged = staging_key(ctx.uid, ctx.sid, upload_id)
            if blobs.exists(staged):
                return staged, False
        for fmt in CANONICAL_TYPES:
            key = original_key(ctx.uid, ctx.sid, fmt)
            if blobs.exists(key):
                return key, True
        return None

    def check_duration(ctx: TaskContext, seconds: float) -> None:
        if seconds > MAX_DURATION_S:
            raise fail(ctx, "audio_too_long")
        if seconds < MIN_DURATION_S:
            raise fail(ctx, "audio_unreadable")

    def validate(ctx: TaskContext) -> None:
        uid, sid = ctx.uid, ctx.sid
        session = ctx.repo.get_session(uid, sid)
        source = find_source(ctx, session.upload.upload_id if session.upload else None)
        if source is None:
            raise fail(ctx, "audio_unreadable")
        src_key, moved = source

        size = blobs.size(src_key)
        if size is None:
            raise fail(ctx, "audio_unreadable")
        if size > MAX_UPLOAD_BYTES:
            raise fail(ctx, "audio_too_large")

        with tempfile.TemporaryDirectory(prefix="onolys-validate-") as tmp:
            local = Path(tmp) / "in.bin"
            flac = Path(tmp) / "canonical.flac"
            blobs.download_to(src_key, local)
            ctx.check_deadline()

            with local.open("rb") as f:
                fmt = sniff(f.read(64))
            if fmt is None:
                raise fail(ctx, "unsupported_audio")

            try:
                probe = tools.probe(local)
            except ToolError:
                raise fail(ctx, "audio_unreadable") from None
            if probe.video_streams > 0:
                raise fail(ctx, "unsupported_audio")
            if probe.audio_streams < 1:
                raise fail(ctx, "audio_unreadable")
            seconds = probe.duration_s
            if seconds is not None:
                check_duration(ctx, seconds)

            try:
                tools.to_flac(local, flac, None if seconds is not None else UNKNOWN_DURATION_CAP_S)
                if seconds is None:  # header carried no duration: measure the transcoded file
                    seconds = tools.probe(flac).duration_s
            except ToolError:
                raise fail(ctx, "audio_unreadable") from None
            if seconds is None:
                raise fail(ctx, "audio_unreadable")
            check_duration(ctx, seconds)
            ctx.check_deadline()

            orig = original_key(uid, sid, fmt)
            digest, nbytes = _sha256(local), local.stat().st_size
            blobs.upload_from(canonical_key(uid, sid), flac, "audio/flac")
            if moved:
                if src_key != orig:  # sniffed format differs from the earlier attempt's
                    blobs.move(src_key, orig)
            else:
                blobs.move(src_key, orig)  # also deletes the staged object

        ctx.repo.add_recording(
            uid,
            sid,
            "original",
            RecordingDoc(
                gcs_uri=blobs.uri(orig),
                size=nbytes,
                duration_ms=round(seconds * 1000),
                format=fmt,
                sha256=digest,
            ),
        )
        if seconds < SHORT_RECORDING_S and SHORT_WARNING not in session.warnings:
            ctx.repo.update_session(uid, sid, {"warnings": [*session.warnings, SHORT_WARNING]})
        if session.state == "validating":
            advance(ctx.repo, uid, sid, to="transcribing", step="transcribe")
        ctx.enqueue(TaskPayload(kind="transcribe", uid=uid, sid=sid))

    return validate
