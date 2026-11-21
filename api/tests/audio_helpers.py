"""Shared helpers for the audio upload / validate tests (tiny generated fixtures, stub tools)."""

import io
import wave
from pathlib import Path

from onolys_api.audio import ProbeResult, ToolError

A = {"Authorization": "Bearer test:alice"}
B = {"Authorization": "Bearer test:bob"}


def tiny_wav(seconds: float = 1.0, rate: int = 8000) -> bytes:
    """A real, valid mono 16-bit WAV of silence (about 16 KB per second at 8 kHz)."""
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b"\x00\x00" * int(rate * seconds))
    return buf.getvalue()


MAGIC = {
    "mp3": b"ID3\x03\x00\x00\x00\x00\x00\x00" + b"\x00" * 32,
    "wav": tiny_wav(0.1),
    "m4a": b"\x00\x00\x00\x20ftypM4A \x00\x00\x00\x00M4A mp42isom" + b"\x00" * 32,
    "webm": b"\x1a\x45\xdf\xa3" + b"\x00" * 32,
    "ogg": b"OggS\x00\x02" + b"\x00" * 32,
}


class StubTools:
    """Stands in for ffprobe + ffmpeg: returns canned probe results, writes a stub FLAC."""

    def __init__(
        self,
        probe: ProbeResult | None = None,
        flac_probe: ProbeResult | None = None,
        probe_error: bool = False,
        transcode_error: bool = False,
    ) -> None:
        self.result = probe or ProbeResult(duration_s=60.0, audio_streams=1, video_streams=0)
        self.flac_result = flac_probe or ProbeResult(duration_s=60.0, audio_streams=1)
        self.probe_error = probe_error
        self.transcode_error = transcode_error
        self.probed: list[str] = []
        self.transcoded: list[tuple[str, float | None]] = []

    def probe(self, path: Path) -> ProbeResult:
        self.probed.append(path.name)
        if self.probe_error:
            raise ToolError("ffprobe failed")
        return self.flac_result if path.suffix == ".flac" else self.result

    def to_flac(self, src: Path, dst: Path, max_seconds: float | None = None) -> None:
        self.transcoded.append((src.name, max_seconds))
        if self.transcode_error:
            raise ToolError("ffmpeg failed")
        dst.write_bytes(b"fLaC-stub")
