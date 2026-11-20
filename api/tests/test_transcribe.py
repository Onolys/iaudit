"""R4 Transcribe / D16 / AC6: `transcribe` + `transcribe-poll`. Fake clock and queue, no sleeps."""

from datetime import UTC, datetime, timedelta

import pytest
from onolys_core.stt import Word
from onolys_core.stt.fixture import FixtureStt, uri_hash

from onolys_api.adapters import AdapterError, FakeStt
from onolys_api.audio import canonical_key
from onolys_api.jobs import transcribe as tr
from onolys_api.jobs.queue import InMemoryQueue, TaskPayload
from onolys_api.jobs.transcribe import make_poll_handler, make_transcribe_handler
from onolys_api.jobs.worker import HandlerSpec, TaskRunner
from onolys_api.repo.base import NotFoundError
from onolys_api.repo.fake import FakeRepo
from onolys_api.repo.models import RecordingDoc, SessionDoc, SessionStatusDoc, SttInfo

pytestmark = pytest.mark.unit
UID, SID = "u1", "s1"
T0 = datetime(2026, 1, 1, tzinfo=UTC)


class Clock:
    def __init__(self) -> None:
        self.now = T0

    def __call__(self) -> datetime:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += timedelta(seconds=seconds)


class RecQueue(InMemoryQueue):
    def __init__(self) -> None:
        super().__init__()
        self.delays: list[tuple[str, int | None, float]] = []

    def enqueue(self, payload, delay_s: float = 0.0) -> None:
        self.delays.append((payload.kind, payload.n, delay_s))
        super().enqueue(payload, delay_s)


class FlakyPollStt(FakeStt):
    """First `poll` raises a retryable provider error."""

    def __init__(self, **kw) -> None:
        super().__init__(**kw)
        self.fail_next = True

    async def poll(self, handle):
        if self.fail_next:
            self.fail_next = False
            raise AdapterError("upstream_unavailable")
        return await super().poll(handle)


def words(counts: dict[str, int]) -> list[Word]:
    out, t = [], 0
    for spk, n in counts.items():
        for i in range(n):
            out.append(Word(text=f"w{i}", start_ms=t, end_ms=t + 300, speaker=spk))
            t += 300
        t += 3000  # gap: separate turns
    return out


class Env:
    def __init__(self, blobs, stt, title=None) -> None:
        self.clock = Clock()
        self.repo = FakeRepo(blobs)
        self.blobs = blobs
        self.queue = RecQueue()
        self.stt = stt
        self.hook_calls: list[tuple[str, str]] = []
        self.runner = TaskRunner(self.repo, self.queue, self.clock)
        self.runner.register(
            "transcribe",
            HandlerSpec(make_transcribe_handler(blobs, stt), step="transcribe", complete=False),
        )
        self.runner.register(
            "transcribe-poll",
            HandlerSpec(make_poll_handler(blobs, stt, self.hook), step="transcribe", claim=False),
        )
        self.repo.create_session(
            UID, SID,
            SessionDoc(uid=UID, state="transcribing", step="transcribe", title=title,
                       stt=SttInfo(provider="p", model="m", language="en")),
            SessionStatusDoc(uid=UID, state="transcribing", step="transcribe", progress=20),
        )  # fmt: skip
        self.repo.add_recording(
            UID, SID, "original", RecordingDoc(gcs_uri="gs://b/x", duration_ms=600_000)
        )

    def hook(self, repo, queue, uid, sid) -> None:
        self.hook_calls.append((uid, sid))

    def start(self, retry: int = 0):
        return self.runner.handle(TaskPayload(kind="transcribe", uid=UID, sid=SID), retry)

    def poll(self, n: int, retry: int = 0):
        return self.runner.handle(TaskPayload(kind="transcribe-poll", uid=UID, sid=SID, n=n), retry)

    def run_polls(self, limit: int = 200) -> None:
        """Deliver queued polls in order, advancing the clock by each poll's delay."""
        for _ in range(limit):
            if not self.queue.pending:
                return
            p = self.queue.pending.pop(0)
            self.clock.advance(self.queue.delays[-1][2])
            self.runner.handle(p, 0)
        raise AssertionError("poll limit")

    @property
    def session(self):
        return self.repo.get_session(UID, SID)


def fixture_stt(blobs, counts, **kw) -> FixtureStt:
    uri = blobs.uri(canonical_key(UID, SID))
    return FixtureStt({uri_hash(uri): words(counts)}, **kw)


@pytest.fixture
def make_env(blobs):
    def make(counts=None, stt=None, title=None) -> Env:
        return Env(
            blobs,
            stt or fixture_stt(blobs, {"A": 60, "B": 60} if counts is None else counts),
            title,
        )

    return make


# ---- success ----


def test_start_stores_operation_and_enqueues_delayed_poll(make_env):
    env = make_env()
    assert env.start().status_code == 200
    s = env.session
    assert env.stt.submits == 1
    assert s.steps["transcribe"].stt_operation.startswith("fixture:")
    assert s.steps["transcribe"].status == "pending"  # released: a redelivery can resume
    assert s.state == "transcribing"
    assert env.queue.delays == [("transcribe-poll", 1, 15)]
    assert env.hook_calls == []


def test_start_passes_canonical_audio_and_session_params(blobs):
    stt = FakeStt()
    env = Env(blobs, stt, title="my title")
    env.start()
    audio, params = stt.started[0]
    assert audio.uri == blobs.uri(canonical_key(UID, SID))
    assert audio.mime == "audio/flac" and audio.duration_ms == 600_000
    assert (params.provider, params.model, params.language) == ("p", "m", "en")
    assert (params.diarization, params.speakers_min, params.speakers_max) == (True, 2, 2)
    assert params.options["stub_title"] == "my title"


def test_polls_until_ready_then_awaiting_input(make_env, blobs):
    env = Env(blobs, fixture_stt(blobs, {"A": 60, "B": 60}, polls_before_ready=2))
    env.start()
    env.run_polls()
    assert env.queue.delays == [("transcribe-poll", n, 15) for n in (1, 2, 3)]
    s = env.session
    assert (s.state, s.transcript_ready) == ("awaiting_input", True)
    assert s.steps["transcribe"].status == "done" and s.error is None
    st = env.repo.get_status(UID, SID)
    assert (st.state, st.transcript_ready, st.progress) == ("awaiting_input", True, 40)
    assert len(env.repo.get_transcript(UID, SID, tr.TRANSCRIPT_ID).transcript.turns) == 2
    assert env.hook_calls == [(UID, SID)]
    assert env.stt.submits == 1


def test_three_speakers_reach_the_gate(make_env):
    env = make_env({"A": 100, "B": 60, "C": 20})  # smallest has 11%, second has 33%
    env.start()
    env.run_polls()
    s = env.session
    assert s.state == "awaiting_input" and s.transcript_ready
    turns = env.repo.get_transcript(UID, SID, tr.TRANSCRIPT_ID).transcript.turns
    assert {t.speaker for t in turns} == {"S1", "S2", "S3"}
    assert env.hook_calls == [(UID, SID)]


def test_large_transcript_is_stored_as_a_pointer(make_env):
    env = make_env({"A": 60_000, "B": 60_000})
    env.start()
    env.run_polls()
    raw = env.repo.get_transcript(UID, SID, tr.TRANSCRIPT_ID, resolve=False)
    assert raw.transcript is None and raw.pointer is not None
    assert raw.pointer.size_bytes > 500 * 1024
    assert env.session.state == "awaiting_input"


# ---- exactly-once start (D16, AC6) ----


def test_redelivered_transcribe_resumes_and_never_resubmits(make_env):
    env = make_env()
    env.start()
    op = env.session.steps["transcribe"].stt_operation
    env.start()  # redelivery (also covers a retry after a crash past the stored handle)
    env.start(retry=1)
    assert env.stt.submits == 1
    assert env.session.steps["transcribe"].stt_operation == op
    assert [d for d in env.queue.delays if d[0] == "transcribe-poll"][0] == (
        "transcribe-poll",
        1,
        15,
    )
    env.run_polls()
    assert env.session.state == "awaiting_input" and env.stt.submits == 1


def test_start_after_done_is_a_duplicate(make_env):
    env = make_env()
    env.start()
    env.run_polls()
    assert env.start().outcome == "duplicate"
    assert env.stt.submits == 1 and env.hook_calls == [(UID, SID)]


def test_poll_retry_after_provider_error_does_not_resubmit(blobs):
    stt = FlakyPollStt()
    env = Env(blobs, stt)
    env.start()
    p = env.queue.pending.pop(0)
    first = env.runner.handle(p, 0)  # retryable: 503, Cloud Tasks retries the same task
    assert (first.status_code, first.outcome) == (503, "retry")
    assert env.runner.handle(p, 1).outcome == "done"
    assert stt.start_calls == 1
    assert env.session.state == "awaiting_input"


def test_provider_error_twice_fails_transcription(blobs):
    stt = FlakyPollStt()
    env = Env(blobs, stt)
    env.start()
    p = env.queue.pending.pop(0)
    stt.fail_next = True
    env.runner.handle(p, 0)
    stt.fail_next = True
    assert env.runner.handle(p, 1).outcome == "failed"
    assert env.session.error.code == "transcription_failed"
    assert stt.start_calls == 1


def test_duplicate_poll_after_done_is_a_noop(make_env):
    env = make_env()
    env.start()
    p = env.queue.pending[0]
    env.run_polls()
    assert env.poll(p.n).status_code == 200
    assert env.hook_calls == [(UID, SID)] and env.session.state == "awaiting_input"


# ---- time limit ----


def test_polls_stop_at_the_time_limit(blobs):
    env = Env(blobs, fixture_stt(blobs, {"A": 60, "B": 60}, polls_before_ready=10**6))
    env.start()
    env.run_polls()
    s = env.session
    assert (s.state, s.error.code, s.error.step) == ("failed", "transcription_failed", "transcribe")
    assert s.steps["transcribe"].status == "failed"
    assert env.repo.get_status(UID, SID).error_code == "transcription_failed"
    polls = [d for d in env.queue.delays if d[0] == "transcribe-poll"]
    assert 70 <= len(polls) <= 90  # about 20 min / 15 s
    assert env.clock.now - T0 <= timedelta(minutes=21)
    assert env.hook_calls == []


def test_a_result_at_the_limit_is_still_taken(blobs):
    env = Env(blobs, fixture_stt(blobs, {"A": 60, "B": 60}))
    env.start()
    env.clock.advance(tr.STT_TIME_LIMIT_S + 5)
    env.runner.handle(env.queue.pending.pop(0), 0)
    assert env.session.state == "awaiting_input"


# ---- outcome checks ----


@pytest.mark.parametrize(
    ("counts", "code"),
    [
        ({}, "no_speech"),  # 0 turns
        ({"A": 25, "B": 24}, "no_speech"),  # 49 words
        ({"A": 80}, "speakers_not_separated"),  # one speaker
        ({"A": 95, "B": 5}, "speakers_not_separated"),  # second speaker 5%
        ({"A": 100, "B": 3, "C": 3}, "speakers_not_separated"),  # no second real speaker
    ],
)
def test_bad_transcripts_fail_with_code(make_env, counts, code):
    env = make_env(counts)
    env.start()
    env.run_polls()
    s = env.session
    assert (s.state, s.error.code, s.error.step) == ("failed", code, "transcribe")
    assert not s.transcript_ready and s.steps["transcribe"].status == "failed"
    assert env.repo.get_status(UID, SID).error_code == code
    assert env.hook_calls == []
    with pytest.raises(NotFoundError):  # nothing stored
        env.repo.get_transcript(UID, SID, tr.TRANSCRIPT_ID)


def test_exactly_fifty_words_and_ten_percent_pass(make_env):
    env = make_env({"A": 45, "B": 5})
    env.start()
    env.run_polls()
    assert env.session.state == "awaiting_input"


@pytest.mark.parametrize(
    ("marker", "code"),
    [
        ("[fail:no_speech]", "no_speech"),
        ("[fail:speakers_not_separated]", "speakers_not_separated"),
        ("[fail:transcription_failed]", "transcription_failed"),
    ],
)
def test_fake_stt_magic_titles(blobs, marker, code):
    env = Env(blobs, FakeStt(), title=f"x {marker}")
    env.start()
    env.run_polls()
    assert (env.session.state, env.session.error.code) == ("failed", code)


def test_fake_stt_happy_path_reaches_gate(blobs):
    env = Env(blobs, FakeStt(polls_before_ready=1))
    env.start()
    env.run_polls()
    assert env.session.state == "awaiting_input"


def test_start_without_session_stt_fails_internal(make_env):
    env = make_env()
    env.repo.update_session(UID, SID, {"stt": None})
    assert env.start().outcome == "failed"
    assert env.session.error.code == "internal_error"


def test_not_transcribing_is_a_noop(make_env):
    env = make_env()
    env.repo.update_session(UID, SID, {"state": "deleting"})
    env.start()
    assert env.stt.submits == 0


# ---- app wiring ----


def test_app_registers_both_handlers(settings, blobs):
    from onolys_api.app import create_app

    app = create_app(settings, repo=FakeRepo(blobs), blobs=blobs)
    assert app.state.runner.has("transcribe") and app.state.runner.has("transcribe-poll")


# ---- observability: Chirp operation name + poll progress in the logs ----


def _events(caplog, event):
    import json

    out = []
    for r in caplog.records:
        if r.name.startswith("onolys_api"):
            try:
                d = json.loads(r.getMessage())
            except ValueError:
                continue
            if d.get("event") == event:
                out.append(d)
    return out


def test_start_logs_operation_name_and_stt_started(make_env, caplog):
    import logging

    env = make_env()
    with caplog.at_level(logging.INFO):
        env.start()
    (d,) = _events(caplog, "stt_started")
    op = env.session.steps["transcribe"].stt_operation
    assert d["stt_operation"] == op  # bare handle (no wrapper) is logged as is
    assert d["stt_started"] == T0.isoformat()
    assert (d["session_id"], d["step"]) == (SID, "transcribe")
    assert not any(k in d for k in ("text", "transcript", "uid"))


def test_operation_name_unwraps_the_provider_router_handle():
    import json

    wrapped = json.dumps({"provider": "google-chirp", "handle": "projects/p/operations/123"})
    assert tr.operation_name(wrapped) == "projects/p/operations/123"
    assert tr.operation_name("fake:abc") == "fake:abc"
    assert tr.operation_name(None) is None


def test_every_poll_logs_number_elapsed_and_operation(blobs, caplog):
    import logging

    env = Env(blobs, fixture_stt(blobs, {"A": 60, "B": 60}, polls_before_ready=2))
    with caplog.at_level(logging.INFO):
        env.start()
        env.run_polls()
    op = env.session.steps["transcribe"].stt_operation
    polls = _events(caplog, "stt_poll")
    assert [(d["poll_n"], d["elapsed_s"], d["outcome"]) for d in polls] == [
        (1, 15, "pending"), (2, 30, "pending"), (3, 45, "ready"),
    ]  # fmt: skip
    assert all(d["stt_operation"] == op and d["session_id"] == SID for d in polls)
    assert all("transcript" not in d and "text" not in d for d in polls)
