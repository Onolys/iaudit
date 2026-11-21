"""SP09 Task 1 (R3, D2, D3, AC2): one table turns any engine exception into one public code."""

import json
import logging

import pytest
import test_run
import test_worker
from google.api_core.exceptions import ServiceUnavailable, TooManyRequests
from onolys_core.errors import ConfigError, InputError, OnolysError, PackError
from onolys_core.llm.errors import (
    FixtureMiss,
    LLMBadOutput,
    LLMRateLimited,
    LLMTimeout,
    LLMUnavailable,
)
from onolys_core.stt.google_chirp import SttProviderError
from test_logging import failed
from test_run import swap_eval
from test_worker import SID, payload, runner_with

from onolys_api.adapters import AdapterError, FakeEvaluation
from onolys_api.adapters.error_map import PUBLIC_MESSAGES, to_public
from onolys_api.errors import ERROR_CODES
from onolys_api.jobs.worker import MAX_ATTEMPTS

paudit = pytest.importorskip("paudit")
eaudit = pytest.importorskip("eaudit")
from eaudit.api.errors import DeadlineExceeded as EauditDeadline  # noqa: E402
from paudit.code_pass import CodePassFailed  # noqa: E402
from paudit.engine import AllRunsFailed  # noqa: E402
from paudit.globals_pass import GlobalsPassFailed  # noqa: E402

env = test_run.env
repo = test_worker.repo
SECRET = "SECRET-transcript-text"
UPSTREAM, DEADLINE, TRANSCRIBE = "upstream_unavailable", "deadline_exceeded", "transcription_failed"

# (id, exception factory, stage, attempt, public code, retryable)
CASES = [
    ("input", lambda: InputError(SECRET), "run", 1, "invalid_parameters", False),
    ("pack", lambda: PackError(SECRET), "run", 1, "internal_error", False),
    ("config", lambda: ConfigError(SECRET), "run", 1, "internal_error", False),
    ("llm_unavailable", lambda: LLMUnavailable(SECRET), "run", 1, UPSTREAM, True),
    ("llm_timeout", lambda: LLMTimeout(SECRET), "run", 1, UPSTREAM, True),
    ("llm_rate_limited", lambda: LLMRateLimited(SECRET, 3.0), "run", 1, UPSTREAM, True),
    ("llm_bad_output", lambda: LLMBadOutput(SECRET), "run", 1, UPSTREAM, True),
    ("llm_fixture_miss", lambda: FixtureMiss(SECRET), "run", 1, "internal_error", False),
    ("llm_bad_output_a2", lambda: LLMBadOutput(SECRET), "run", 2, UPSTREAM, True),
    ("deadline_builtin", lambda: TimeoutError(SECRET), "run", 1, DEADLINE, True),
    ("deadline_eaudit", lambda: EauditDeadline(SECRET), "run", 1, DEADLINE, True),
    ("code_pass_failed", lambda: CodePassFailed(SECRET), "run", 1, "internal_error", False),
    ("globals_pass_failed", lambda: GlobalsPassFailed(SECRET), "run", 1, "internal_error", False),
    ("all_runs_failed", lambda: AllRunsFailed(SECRET), "run", 1, "internal_error", False),
    ("unknown", lambda: ValueError(SECRET), "run", 1, "internal_error", False),
    ("onolys_base", lambda: OnolysError(SECRET), "run", 1, "internal_error", False),
    ("adapter_upstream", lambda: AdapterError(UPSTREAM), "run", 1, UPSTREAM, True),
    ("adapter_paudit", lambda: AdapterError("paudit_failed"), "run", 1, "internal_error", False),
    ("stt_transient_a1", lambda: ServiceUnavailable(SECRET), "stt", 1, UPSTREAM, True),
    ("stt_429_a1", lambda: TooManyRequests(SECRET), "stt", 1, UPSTREAM, True),
    ("stt_transient_a2", lambda: ServiceUnavailable(SECRET), "stt", 2, TRANSCRIBE, False),
    ("stt_flagged_a1", lambda: _transient_provider_error(), "stt", 1, UPSTREAM, True),
    ("stt_flagged_a2", lambda: _transient_provider_error(), "stt", 2, TRANSCRIBE, False),
    ("stt_permanent", lambda: SttProviderError(SECRET), "stt", 1, TRANSCRIBE, False),
    ("stt_permanent_a2", lambda: SttProviderError(SECRET), "stt", 2, TRANSCRIBE, False),
    ("stt_adapter_code", lambda: AdapterError(TRANSCRIBE), "stt", 1, TRANSCRIBE, False),
    ("stt_adapter_upstream", lambda: AdapterError(UPSTREAM), "stt", 1, UPSTREAM, True),
    ("stt_adapter_upstream_a2", lambda: AdapterError(UPSTREAM), "stt", 2, TRANSCRIBE, False),
    ("stt_unknown", lambda: ValueError(SECRET), "stt", 1, "internal_error", False),
    # transcript outcomes carried by adapter codes (SP04 R4 checks)
    ("no_speech", lambda: AdapterError("no_speech"), "stt", 1, "no_speech", False),
    ("not_separated", lambda: AdapterError("speakers_not_separated"), "stt", 1,
     "speakers_not_separated", False),
]  # fmt: skip


def _chained(outer, cause):
    try:
        raise cause
    except Exception as c:
        try:
            raise outer from c
        except Exception as e:
            return e


def _context_only(outer, inner):
    try:
        raise inner
    except Exception:
        try:
            raise outer  # implicit __context__, no explicit cause
        except Exception as e:
            return e


CASES += [
    ("all_runs_from_llm_unavailable",
     lambda: _chained(AllRunsFailed(SECRET), LLMUnavailable(SECRET)), "run", 1, UPSTREAM, True),
    ("all_runs_from_llm_timeout",
     lambda: _chained(AllRunsFailed(SECRET), LLMTimeout(SECRET)), "run", 1, UPSTREAM, True),
    ("all_runs_from_fixture_miss",
     lambda: _chained(AllRunsFailed(SECRET), FixtureMiss(SECRET)), "run", 1,
     "internal_error", False),
    ("all_runs_from_onolys_base",
     lambda: _chained(AllRunsFailed(SECRET), OnolysError(SECRET)), "run", 1,
     "internal_error", False),
    ("all_runs_context_llm",
     lambda: _context_only(AllRunsFailed(SECRET), LLMUnavailable(SECRET)), "run", 1, UPSTREAM, True),
    ("all_runs_no_cause", lambda: AllRunsFailed(SECRET), "run", 1, "internal_error", False),
]  # fmt: skip


def _transient_provider_error() -> SttProviderError:
    e = SttProviderError(SECRET)
    e.transient = True  # type: ignore[attr-defined]
    return e


IDS = [c[0] for c in CASES]


@pytest.mark.parametrize("make,stage,attempt,code,retryable", [c[1:] for c in CASES], ids=IDS)
def test_to_public_table(make, stage, attempt, code, retryable):
    assert to_public(make(), attempt=attempt, stage=stage) == (code, retryable)


def test_every_mapped_code_is_a_public_code_with_fixed_message():
    codes = {c[4] for c in CASES}
    assert codes <= set(ERROR_CODES)
    for code in codes:
        assert PUBLIC_MESSAGES[code] and SECRET not in PUBLIC_MESSAGES[code]


def test_message_is_never_the_exception_message():
    code, _ = to_public(InputError(SECRET))
    assert SECRET not in PUBLIC_MESSAGES[code]


# ---- through SP04's handler wrapper: one `status=failed` line, exc_class only, no text ----


@pytest.mark.parametrize("make,stage,attempt,code,retryable", [c[1:] for c in CASES], ids=IDS)
def test_wrapper_records_code_and_one_failed_line(repo, caplog, make, stage, attempt, code,
                                                  retryable):  # fmt: skip
    exc = make()
    step = "transcribe" if stage == "stt" else "validate"

    def fn(ctx):
        raise exc

    runner = runner_with(repo, fn, kind=step if stage == "stt" else "validate")
    caplog.clear()
    with caplog.at_level(logging.INFO):
        r = runner.handle(payload(step if stage == "stt" else "validate"), retry_count=attempt - 1)
    last = attempt >= MAX_ATTEMPTS
    if retryable and not last:
        assert (r.status_code, r.outcome) == (503, "retry") and failed(caplog) == []
        return
    assert (r.status_code, r.outcome) == (200, "failed")
    s = repo.get_session(test_worker.UID, SID)
    assert s.state == "failed" and s.error.code == code
    (f,) = failed(caplog)
    assert (f["error_code"], f["exc_class"], f["request_id"]) == (code, type(exc).__name__, "req-1")
    assert SECRET not in caplog.text and SECRET not in s.model_dump_json()
    assert SECRET not in json.dumps(repo.get_status(test_worker.UID, SID).model_dump(mode="json"))


# ---- the run path: stubbed engine raises the engine class; API body carries no message ----


@pytest.mark.parametrize(
    "make,code",
    [
        (lambda: InputError(SECRET), "invalid_parameters"),
        (lambda: PackError(SECRET), "internal_error"),
        (lambda: LLMUnavailable(SECRET), UPSTREAM),
        (lambda: LLMBadOutput(SECRET), UPSTREAM),
        (lambda: CodePassFailed(SECRET), "internal_error"),
        (lambda: EauditDeadline(SECRET), DEADLINE),
    ],
    ids=["input", "pack", "llm", "bad_output", "code_pass", "deadline"],
)
async def test_stubbed_engine_failure_maps_through_run_and_status_body(env, caplog, make, code):
    class Boom(FakeEvaluation):
        async def run(self, *a, **kw):
            raise make()

    swap_eval(env, Boom())
    with caplog.at_level(logging.INFO):
        sid = await env.finished()
    s = env.repo.get_session(env.uid, sid)
    assert s.state == "failed" and s.error.code == code
    (run,) = env.repo.list_runs(env.uid, sid)
    assert run.status == "failed" and run.error == code
    (f,) = failed(caplog)
    assert (f["error_code"], f["exc_class"]) == (code, type(make()).__name__)
    assert f["request_id"] and f["run_id"] == run.run_id
    body = (await env.c.get(f"/v1/sessions/{sid}", headers=env.h)).text
    assert SECRET not in body and SECRET not in caplog.text
    assert env.counters()[0] == 0  # slot released once
