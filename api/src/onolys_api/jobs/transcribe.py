"""The `transcribe` and `transcribe-poll` steps (PRD R4, D16, AC6).

`transcribe` calls `Stt.start` once, stores the handle as `steps.transcribe.stt_operation` (with
`stt_started`), releases its claim and enqueues the first delayed poll. A retry or redelivery
finds `stt_operation` and only resumes polling: it never re-submits. (A crash between `start`
returning and the handle being stored can still submit twice: the provider API offers no
idempotency key.) Each poll task asks `Stt.poll` once; no result re-enqueues the next poll
(`{sid}-poll-{n}`, ~15 s apart) until the cap, then `transcription_failed`. The cap is
`clamp(factor x audio duration, min, max)` (settings, default 3x, 300 s..1200 s), stored on the
step as `stt_limit_s`. The next poll is queued BEFORE the provider is asked, so a poll that dies
(or whose retries run out) cannot break the chain; a failed enqueue fails the request (5xx, Cloud
Tasks retries the same poll; terminal `transcription_failed` on the last attempt). A chain that
still stops is failed lazily on read (`jobs/stale.py`).

A finished transcript is checked (`no_speech`, `speakers_not_separated`), stored (pointer when
over 500 KB, by the repo), and the session moves to `awaiting_input` with `transcript_ready`.
Logs carry codes and ids only, never transcript text.
"""

import asyncio
import json
import threading
from collections import Counter
from collections.abc import Callable
from typing import Any

from onolys_core.stt import SttParams
from onolys_core.transcript import Transcript

from onolys_api import logs
from onolys_api.adapters.base import AdapterError, Stt
from onolys_api.audio import canonical_audio_ref
from onolys_api.config import Settings
from onolys_api.jobs.first_run import maybe_start_first_run
from onolys_api.jobs.machine import advance
from onolys_api.jobs.queue import MAX_ATTEMPTS, TaskPayload, TaskQueue
from onolys_api.jobs.worker import (
    RETRYABLE_CODES,
    Handler,
    PermanentError,
    RetryableError,
    TaskContext,
)
from onolys_api.repo.base import Repo
from onolys_api.storage.base import BlobStore

TRANSCRIPT_ID = "current"
POLL_INTERVAL_S = 15.0
STT_TIME_LIMIT_S = 20 * 60.0  # default cap maximum (Settings.stt_time_limit_s)
MIN_WORDS = 50
MIN_SECOND_SPEAKER_SHARE = 0.10
STEP = "transcribe"

FirstRunHook = Callable[[Repo, TaskQueue, str, str], None]


def _run(coro) -> Any:
    """Run an adapter coroutine from a sync handler (threadpool worker; also safe in a loop)."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    box: list[Any] = []

    def target() -> None:
        try:
            box.append((True, asyncio.run(coro)))
        except BaseException as e:  # noqa: BLE001 - re-raised below
            box.append((False, e))

    t = threading.Thread(target=target)
    t.start()
    t.join()
    ok, val = box[0]
    if not ok:
        raise val
    return val


def _provider_error(e: AdapterError, ctx: TaskContext) -> Exception:
    """Retryable provider errors retry once; everything else (and the last attempt) is the
    public `transcription_failed`."""
    if e.code in RETRYABLE_CODES and ctx.attempt < MAX_ATTEMPTS:
        return RetryableError(e.code)
    return PermanentError("transcription_failed")


def check_transcript(transcript: Transcript) -> str | None:
    """The failure code for a finished transcript, or None when it can reach the gate.

    `no_speech`: no turns or under 50 words. `speakers_not_separated`: fewer than 2 speakers,
    or the second-largest speaker has under 10% of the words (with 3+ speakers a small extra
    speaker is fine; the gate lists them all).
    """
    per_speaker: Counter[str] = Counter()
    total = 0
    for turn in transcript.turns:
        n = len(turn.text.split())
        total += n
        if turn.speaker is not None:
            per_speaker[turn.speaker] += n
    if not transcript.turns or total < MIN_WORDS:
        return "no_speech"
    ranked = [n for _, n in per_speaker.most_common()]
    if len(ranked) < 2 or ranked[1] < MIN_SECOND_SPEAKER_SHARE * total:
        return "speakers_not_separated"
    return None


def operation_name(handle: Any) -> str | None:
    """The provider operation name inside a stored STT handle (ids only, never text).

    The real router stores `{"provider", "handle"}` JSON, where `handle` is the Chirp operation
    name; fakes store a bare string.
    """
    if handle is None:
        return None
    if isinstance(handle, str):
        try:
            inner = json.loads(handle)
        except ValueError:
            return handle
        if isinstance(inner, dict) and isinstance(inner.get("handle"), str):
            return inner["handle"]
    return str(handle)


def stt_cap_s(audio_s: float | None, settings: Settings | None = None) -> float:
    """The poll cap for a recording: `clamp(factor x duration, min, max)`; the maximum when the
    duration is unknown."""
    s = settings or Settings()
    if audio_s is None:
        return s.stt_time_limit_s
    return min(s.stt_time_limit_s, max(s.stt_cap_min_s, s.stt_cap_factor * audio_s))


def _poll_payload(ctx: TaskContext, n: int) -> TaskPayload:
    return TaskPayload(kind="transcribe-poll", uid=ctx.uid, sid=ctx.sid, n=n)


def make_transcribe_handler(
    blobs: BlobStore, stt: Stt, *, settings: Settings | None = None
) -> Handler:
    """Register with `HandlerSpec(fn, step="transcribe", complete=False)`: the step is marked
    `done` by the poll that finishes it."""

    def transcribe(ctx: TaskContext) -> None:
        uid, sid = ctx.uid, ctx.sid
        session = ctx.repo.get_session(uid, sid)
        if session.state != "transcribing":
            return
        rec = session.steps.get(STEP)
        if rec is None or rec.stt_operation is None:
            recs = ctx.repo.list_recordings(uid, sid)
            if not recs or session.stt is None:
                raise PermanentError("internal_error")
            audio = canonical_audio_ref(blobs, uid, sid, recs[0])
            params = SttParams(
                provider=session.stt.provider,
                model=session.stt.model,
                language=session.stt.language or session.language,
                options={"stub_title": session.title},  # real adapters ignore it
            )
            try:
                handle = _run(stt.start(audio, params))
            except AdapterError as e:
                raise _provider_error(e, ctx) from None
            started = ctx.clock()
            ms = recs[0].duration_ms
            limit = stt_cap_s(None if ms is None else ms / 1000, settings)
            ctx.repo.update_session(
                uid, sid,
                {f"steps.{STEP}.stt_operation": handle, f"steps.{STEP}.stt_started": started,
                 f"steps.{STEP}.stt_limit_s": limit},
            )  # fmt: skip
            logs.emit(
                "stt_started", session_id=sid, step=STEP, request_id=ctx.request_id,
                stt_operation=operation_name(handle), stt_started=started.isoformat(),
            )  # fmt: skip
        # release the claim: a redelivery resumes polling instead of waiting out the lease
        ctx.repo.update_session(uid, sid, {f"steps.{STEP}.status": "pending"})
        ctx.enqueue(_poll_payload(ctx, 1), POLL_INTERVAL_S)  # deduped by name on a resume

    return transcribe


def make_poll_handler(
    blobs: BlobStore,
    stt: Stt,
    first_run_hook: FirstRunHook | None = None,
    *,
    settings: Settings | None = None,
) -> Handler:
    """Register with `HandlerSpec(fn, step="transcribe", claim=False)`: the step record belongs
    to `transcribe`; a failure here is recorded on it. `first_run_hook` defaults to the real
    first-run gate bound to `settings` (cap, code version)."""
    if first_run_hook is None:
        if settings is None:
            raise ValueError("settings or first_run_hook is required")
        gate_settings = settings

        def first_run_hook(repo, queue, uid, sid):  # noqa: F811
            maybe_start_first_run(repo, queue, uid, sid, gate_settings)

    def finish(ctx: TaskContext) -> None:
        ctx.repo.update_session(
            ctx.uid, ctx.sid,
            {f"steps.{STEP}.status": "done", f"steps.{STEP}.ended": ctx.clock(),
             f"steps.{STEP}.error": None},
        )  # fmt: skip

    def poll(ctx: TaskContext) -> None:
        uid, sid = ctx.uid, ctx.sid
        session = ctx.repo.get_session(uid, sid)
        rec = session.steps.get(STEP)
        if rec is None or rec.status in ("done", "failed"):
            return
        if session.state == "awaiting_input":  # advanced earlier, crashed before the rest
            finish(ctx)
            first_run_hook(ctx.repo, ctx.queue, uid, sid)
            return
        if session.state != "transcribing":
            return
        if rec.stt_operation is None:
            raise PermanentError("internal_error")

        n = ctx.payload.n or 1
        limit = rec.stt_limit_s or (settings or Settings()).stt_time_limit_s
        started = rec.stt_started or ctx.clock()
        elapsed = (ctx.clock() - started).total_seconds()
        if elapsed < limit:
            # queue the next poll first: it survives this poll dying or running out of attempts.
            # A failure here propagates (5xx, Cloud Tasks retries this same poll; terminal on the
            # last attempt) and a retry re-enqueues the same name (deduped), never a second chain.
            ctx.enqueue(_poll_payload(ctx, n + 1), POLL_INTERVAL_S)

        try:
            transcript = _run(stt.poll(rec.stt_operation))
        except AdapterError as e:
            raise _provider_error(e, ctx) from None

        logs.emit(
            "stt_poll", session_id=sid, step=STEP, request_id=ctx.request_id,
            stt_operation=operation_name(rec.stt_operation), poll_n=n,
            elapsed_s=round(elapsed), outcome="pending" if transcript is None else "ready",
        )  # fmt: skip
        if transcript is None:
            if elapsed >= limit:
                raise PermanentError("transcription_failed")
            return

        code = check_transcript(transcript)
        if code is not None:
            raise PermanentError(code)
        ctx.repo.put_transcript(uid, sid, TRANSCRIPT_ID, transcript)
        advance(ctx.repo, uid, sid, to="awaiting_input", step=None,
                flags={"transcript_ready": True})  # fmt: skip
        finish(ctx)
        first_run_hook(ctx.repo, ctx.queue, uid, sid)

    return poll
