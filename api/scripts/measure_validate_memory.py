"""Measure peak memory of the `validate` step on a synthetic recording (PRD risk: validate memory).

    uv run --package onolys-api python api/scripts/measure_validate_memory.py [--minutes 25] \
        [--workdir DIR]

Generates a stereo 44.1 kHz 16-bit WAV (sine) with ffmpeg in WORKDIR (default: a temp dir next
to this script, removed afterwards), stages it in a FakeBlobStore, runs the real handler with
real ffprobe/ffmpeg, and prints peak RSS: this process (the Python worker) and the largest child
(ffmpeg). Peak working set of the worker ~ max(parent) + max(child) at worst. Linux only.
"""

import argparse
import resource
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

from onolys_api.audio import FfmpegTools, staging_key
from onolys_api.jobs.queue import InMemoryQueue, TaskPayload
from onolys_api.jobs.validate import make_validate_handler
from onolys_api.jobs.worker import HandlerSpec, TaskRunner
from onolys_api.repo.fake import FakeRepo
from onolys_api.repo.models import SessionDoc, SessionStatusDoc, UploadInfo
from onolys_api.storage.fake import FakeBlobStore


def mib(kb: int) -> float:
    return kb / 1024


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--minutes", type=float, default=25.0)
    ap.add_argument("--workdir", default=None)
    args = ap.parse_args()
    work = Path(args.workdir) if args.workdir else Path(tempfile.mkdtemp(dir=Path(__file__).parent))
    work.mkdir(parents=True, exist_ok=True)
    try:
        wav = work / "sample.wav"
        subprocess.run(
            ["ffmpeg", "-nostdin", "-v", "error", "-y", "-f", "lavfi", "-i",
             f"sine=frequency=300:duration={args.minutes * 60}", "-ac", "2", "-ar", "44100",
             "-c:a", "pcm_s16le", str(wav)],
            check=True,
        )  # fmt: skip
        size = wav.stat().st_size
        blobs = FakeBlobStore(work / "blobs")
        repo = FakeRepo(blobs)
        uid, sid, up = "u", "s", "up1"
        repo.create_session(uid, sid, SessionDoc(uid=uid, state="validating"),
                            SessionStatusDoc(uid=uid, state="validating"))  # fmt: skip
        repo.update_session(uid, sid, {"upload": UploadInfo(upload_id=up, format="wav",
                            content_type="audio/wav", size_bytes=size).model_dump()})  # fmt: skip
        blobs.upload_from(staging_key(uid, sid, up), wav, "audio/wav")
        runner = TaskRunner(repo, InMemoryQueue())
        runner.register("validate", HandlerSpec(make_validate_handler(blobs, FfmpegTools()),
                        step="validate"))  # fmt: skip
        t0 = time.monotonic()
        res = runner.handle(TaskPayload(kind="validate", uid=uid, sid=sid))
        dt = time.monotonic() - t0
        flac = blobs.root / uid / sid / "audio" / "canonical.flac"
        print(f"outcome={res.outcome} state={repo.get_session(uid, sid).state} seconds={dt:.1f}")
        print(
            f"input_wav_mib={size / 2**20:.1f} canonical_flac_mib={flac.stat().st_size / 2**20:.1f}"
        )
        print(f"peak_rss_python_mib={mib(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss):.1f}")
        print(f"peak_rss_largest_child_mib="
              f"{mib(resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss):.1f}")  # fmt: skip
    finally:
        if not args.workdir:
            shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    main()
