"""Live STT check (PRD R11, AC11): transcribe a 2-speaker sample through the selected adapter.

    python -m onolys_core.stt.check --audio gs://bucket/sample.wav --preset default

`--audio` is a `gs://` URI (Chirp 3 batch reads from Cloud Storage). Auth is ADC. The Google
project is set explicitly (`--project`, else env GOOGLE_CLOUD_PROJECT, else `onolys`) because the
ADC quota project may be another project. Passes when the transcript has at least 2 speakers,
every turn has `start_ms`/`end_ms`, they are monotonic, and the audio is long enough
(`--min-minutes`, default 10). Prints wall time. Exit code 0 only on pass.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
import time
from dataclasses import dataclass, field

from onolys_core.llm.routes import resolve_preset
from onolys_core.stt import AudioRef, SttParams
from onolys_core.stt.base import transcribe
from onolys_core.stt.select import select_stt
from onolys_core.transcript import Transcript

DEFAULT_PROJECT = "onolys"
DEFAULT_MIN_MINUTES = 10.0
_MIMES = {".wav": "audio/wav", ".mp3": "audio/mpeg", ".flac": "audio/flac", ".m4a": "audio/mp4"}


@dataclass
class CheckResult:
    passed: bool
    wall_s: float
    speakers: int = 0
    turns: int = 0
    duration_ms: int = 0
    language: str | None = None
    problems: list[str] = field(default_factory=list)


def evaluate(
    transcript: Transcript, wall_s: float, min_minutes: float = DEFAULT_MIN_MINUTES
) -> CheckResult:
    """Pure pass/fail logic over a finished transcript."""
    problems: list[str] = []
    turns = transcript.turns
    speakers = {t.speaker for t in turns if t.speaker}
    if not turns:
        problems.append("no turns returned")
    if len(speakers) < 2:
        problems.append(f"found {len(speakers)} speaker(s), need at least 2")
    if any(t.start_ms is None or t.end_ms is None for t in turns):
        problems.append("some turns have no start_ms/end_ms")
    else:
        prev_s = prev_e = 0
        for t in turns:
            if t.start_ms > t.end_ms:
                problems.append(f"turn {t.id}: start_ms > end_ms")
                break
            if t.start_ms < prev_s or t.end_ms < prev_e:
                problems.append(f"turn {t.id}: offsets are not monotonic")
                break
            prev_s, prev_e = t.start_ms, t.end_ms
    duration_ms = transcript.duration_ms or max((t.end_ms or 0 for t in turns), default=0)
    if duration_ms < min_minutes * 60_000:
        problems.append(f"audio covers {duration_ms / 60_000:.1f} min, need {min_minutes:g}+")
    return CheckResult(
        passed=not problems,
        wall_s=wall_s,
        speakers=len(speakers),
        turns=len(turns),
        duration_ms=duration_ms,
        language=transcript.language,
        problems=problems,
    )


def format_result(r: CheckResult) -> str:
    lines = [
        f"wall time: {r.wall_s:.1f}s",
        f"audio covered: {r.duration_ms / 60_000:.1f} min, {r.turns} turns, "
        f"{r.speakers} speakers, language={r.language}",
    ]
    lines += [f"problem: {p}" for p in r.problems]
    lines.append("PASS" if r.passed else "FAIL")
    return "\n".join(lines)


def build_params(
    preset: str | None, language: str | None, project: str | None, *, speakers: int = 2
) -> SttParams:
    """STT params for the preset, with the Google project set explicitly."""
    _, stt_key = resolve_preset(preset)
    params = select_stt(stt_key, language)
    options = dict(params.options)
    if params.provider == "google":
        options["project"] = project or os.environ.get("GOOGLE_CLOUD_PROJECT") or DEFAULT_PROJECT
    return params.model_copy(
        update={"options": options, "speakers_min": speakers, "speakers_max": speakers}
    )


def make_adapter(params: SttParams):
    if params.provider == "google":
        from onolys_core.stt.google_chirp import GoogleChirp3

        return GoogleChirp3()
    raise SystemExit(f"stt.check: no adapter for provider {params.provider!r}")


async def run_check(
    adapter,
    audio: AudioRef,
    params: SttParams,
    *,
    min_minutes: float = DEFAULT_MIN_MINUTES,
    interval_s: float = 10.0,
    max_polls: int | None = None,
    clock=time.monotonic,
) -> CheckResult:
    started = clock()
    transcript = await transcribe(
        adapter, audio, params, interval_s=interval_s, max_polls=max_polls
    )
    return evaluate(transcript, clock() - started, min_minutes)


def main(argv: list[str] | None = None, adapter=None) -> int:
    p = argparse.ArgumentParser(prog="python -m onolys_core.stt.check", description=__doc__)
    p.add_argument("--audio", required=True, help="audio reference, a gs:// URI for Google")
    p.add_argument("--preset", default=None, help="preset name (default: DEFAULT_PRESET)")
    p.add_argument("--language", default=None, help="BCP-47 code or auto (default: auto)")
    p.add_argument("--project", default=None, help=f"Google project (default: {DEFAULT_PROJECT})")
    p.add_argument("--min-minutes", type=float, default=DEFAULT_MIN_MINUTES)
    p.add_argument("--interval-s", type=float, default=10.0, help="poll interval")
    p.add_argument("--timeout-min", type=float, default=30.0, help="give up after this long")
    args = p.parse_args(argv)
    params = build_params(args.preset, args.language, args.project)
    ext = os.path.splitext(args.audio)[1].lower()
    audio = AudioRef(uri=args.audio, mime=_MIMES.get(ext, "audio/wav"))
    adapter = adapter or make_adapter(params)
    max_polls = max(1, int(args.timeout_min * 60 / args.interval_s))
    result = asyncio.run(
        run_check(
            adapter,
            audio,
            params,
            min_minutes=args.min_minutes,
            interval_s=args.interval_s,
            max_polls=max_polls,
        )
    )
    print(format_result(result))
    return 0 if result.passed else 1


if __name__ == "__main__":
    sys.exit(main())
