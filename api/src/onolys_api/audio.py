"""Audio rules and tools (PRD R3, D5): format aliases, magic-byte sniff, ffprobe, ffmpeg.

Browsers send several MIME aliases for one format, so the API maps them to ONE canonical type
per format (pinned in the signed PUT). `validate` trusts only the bytes: it sniffs the magic
bytes, probes with ffprobe, then transcodes to the one format STT sees: FLAC, 16 kHz, mono.
"""

import json
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from onolys_core.stt import AudioRef

from onolys_api.repo.models import RecordingDoc
from onolys_api.storage.base import BlobStore

MIN_DURATION_S = 1.0
DEFAULT_MAX_DURATION_S = 20 * 60.0  # fallback; the real limit is `max_audio_s` on the STT provider
SHORT_RECORDING_S = 10 * 60.0
# when the container carries no duration (browser WebM), cap the transcode this far past the limit
UNKNOWN_DURATION_MARGIN_S = 30.0
FLAC_RATE_HZ = 16_000
CANONICAL_MIME = "audio/flac"
PROBE_TIMEOUT_S = 60
TRANSCODE_TIMEOUT_S = 300

# format -> canonical content type (what `required_headers` pins)
CANONICAL_TYPES: dict[str, str] = {
    "mp3": "audio/mpeg",
    "wav": "audio/wav",
    "m4a": "audio/mp4",
    "webm": "audio/webm",
    "ogg": "audio/ogg",
}
_MIME_ALIASES: dict[str, str] = {
    "audio/mpeg": "mp3", "audio/mp3": "mp3", "audio/x-mp3": "mp3", "audio/mpeg3": "mp3",
    "audio/wav": "wav", "audio/x-wav": "wav", "audio/wave": "wav", "audio/vnd.wave": "wav",
    "audio/mp4": "m4a", "audio/x-m4a": "m4a", "audio/m4a": "m4a",
    "audio/webm": "webm",
    "audio/ogg": "ogg", "application/ogg": "ogg",
}  # fmt: skip
_EXT_ALIASES: dict[str, str] = {
    "mp3": "mp3", "wav": "wav", "wave": "wav", "m4a": "m4a", "mp4": "m4a", "webm": "webm",
    "ogg": "ogg", "oga": "ogg",
}  # fmt: skip


def resolve_format(content_type: str | None, filename_ext: str | None) -> str | None:
    """Map a browser content type (or, when it is empty, the file extension) to a format key.
    An unknown non-empty type is unsupported; it is never rescued by the extension."""
    ct = (content_type or "").split(";", 1)[0].strip().lower()
    if ct:
        return _MIME_ALIASES.get(ct)
    return _EXT_ALIASES.get((filename_ext or "").strip().lstrip(".").lower())


def sniff(head: bytes) -> str | None:
    """Format key from the first bytes of the file, or None."""
    if head[:4] == b"RIFF" and head[8:12] == b"WAVE":
        return "wav"
    if head[:4] == b"OggS":
        return "ogg"
    if head[:4] == b"\x1a\x45\xdf\xa3":
        return "webm"
    if head[4:8] == b"ftyp":
        return "m4a"
    if head[:3] == b"ID3" or (len(head) >= 2 and head[0] == 0xFF and head[1] & 0xE0 == 0xE0):
        return "mp3"
    return None


class ToolError(Exception):
    """ffprobe/ffmpeg failed, timed out or produced unreadable output (message has no content)."""


@dataclass(frozen=True)
class ProbeResult:
    duration_s: float | None  # None when the container carries no duration
    audio_streams: int = 1
    video_streams: int = 0  # attached cover art does not count


class AudioTools(Protocol):
    def probe(self, path: Path) -> ProbeResult: ...
    def to_flac(self, src: Path, dst: Path, max_seconds: float | None = None) -> None: ...


class FfmpegTools:
    """Real tools: `ffprobe` and `ffmpeg` from PATH (both are in the image)."""

    def probe(self, path: Path) -> ProbeResult:
        cmd = ["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path)]
        try:
            out = subprocess.run(
                cmd,
                capture_output=True,
                timeout=PROBE_TIMEOUT_S,
                check=True,
                stdin=subprocess.DEVNULL,
            ).stdout
            info = json.loads(out)
        except (subprocess.SubprocessError, OSError, ValueError):
            raise ToolError("ffprobe failed") from None
        audio = video = 0
        for s in info.get("streams", []):
            kind = s.get("codec_type")
            if kind == "audio":
                audio += 1
            elif kind == "video" and not s.get("disposition", {}).get("attached_pic"):
                video += 1
        return ProbeResult(
            duration_s=_duration(info.get("format", {}).get("duration"), info.get("streams", [])),
            audio_streams=audio,
            video_streams=video,
        )

    def to_flac(self, src: Path, dst: Path, max_seconds: float | None = None) -> None:
        cmd = ["ffmpeg", "-nostdin", "-v", "error", "-y", "-i", str(src), "-map", "0:a:0", "-vn"]
        if max_seconds is not None:
            cmd += ["-t", f"{max_seconds:.3f}"]
        cmd += ["-ac", "1", "-ar", str(FLAC_RATE_HZ), "-c:a", "flac", str(dst)]
        try:
            subprocess.run(
                cmd, capture_output=True, timeout=TRANSCODE_TIMEOUT_S, check=True,
                stdin=subprocess.DEVNULL,
            )  # fmt: skip
        except (subprocess.SubprocessError, OSError):
            raise ToolError("ffmpeg failed") from None
        if not dst.is_file() or dst.stat().st_size == 0:
            raise ToolError("ffmpeg produced no output")


def _duration(fmt_duration, streams: list[dict]) -> float | None:
    for raw in (
        fmt_duration,
        *(s.get("duration") for s in streams if s.get("codec_type") == "audio"),
    ):
        try:
            value = float(raw)
        except (TypeError, ValueError):
            continue
        if value >= 0:
            return value
    return None


# ---- keys + the AudioRef handed to STT ----


def staging_key(uid: str, sid: str, upload_id: str) -> str:
    return f"uploads/{uid}/{sid}/{upload_id}"


def original_key(uid: str, sid: str, fmt: str) -> str:
    return f"{uid}/{sid}/audio/original.{fmt}"


def canonical_key(uid: str, sid: str) -> str:
    return f"{uid}/{sid}/audio/canonical.flac"


def canonical_audio_ref(blobs: BlobStore, uid: str, sid: str, recording: RecordingDoc) -> AudioRef:
    """The `AudioRef` STT receives: the canonical FLAC, never a browser format. `local_path_fn`
    downloads it to a temp file on first use (for adapters that need a local file)."""
    key = canonical_key(uid, sid)
    cache: list[Path] = []

    def local_path() -> Path:
        if not cache:
            dst = Path(tempfile.mkdtemp(prefix="onolys-stt-")) / "canonical.flac"
            blobs.download_to(key, dst)
            cache.append(dst)
        return cache[0]

    return AudioRef(
        uri=blobs.uri(key),
        local_path_fn=local_path,
        mime=CANONICAL_MIME,
        duration_ms=recording.duration_ms,
    )
