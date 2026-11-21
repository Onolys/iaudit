"""Task 9 / R1 / D14 / D15 / AC9: `run_evaluation` orchestration with stub clients only.

paudit and the eaudit pipeline are replaced at the module seams `_run_paudit` / `_run_eaudit`
(canned results from the fixture folder); the tips call goes through a real `StubClient`."""

import asyncio
import json
import logging

import pytest
from _make_fixtures import FULL_RATING, inputs
from eaudit.api.errors import DeadlineExceeded
from eaudit.models import AuditResponse, Status
from onolys_core.engine import RunContext
from onolys_core.llm import LLMBadOutput, MetricsCollector, StubClient
from onolys_core.run_info import RunInfo
from paudit.engine import AllRunsFailed
from test_tips import good

from onolys_evaluation import api
from onolys_evaluation.api import EvaluationOutput, run_evaluation

pytestmark = pytest.mark.unit

STAGES = ["paudit", "eaudit", "tips", "compare", "assemble"]


class Env:
    """Wires the seams; records calls, progress and the order of events."""

    def __init__(self, monkeypatch, *, tips=None, eaudit="ok", paudit="ok", barrier=False):
        kw = inputs("full")
        self.pack, self.transcript = kw["pack"], kw["transcript"]
        self.smap, self.paudit_result = kw["speaker_map"], kw["paudit_result"]
        self.params = kw["params"]
        self.events: list[tuple[str, str]] = []
        self.calls: list[str] = []
        self.barrier = barrier
        self.paudit_up, self.eaudit_up = asyncio.Event(), asyncio.Event()
        stub = StubClient()
        replies = tips if tips is not None else [good(3)]

        def handler(req):
            self.calls.append("tips")
            r = replies[min(len(self.calls_of("tips")) - 1, len(replies) - 1)]
            if isinstance(r, BaseException):
                raise r
            return {"tips": r}

        for tag in ("tips:r0", "tips:r0:retry"):
            stub.register(tag, handler)
        self.ctx = RunContext(llm=stub, metrics=MetricsCollector(), request_id="req-1")

        async def fake_paudit(transcript, pack, params, ctx, metrics):
            self.calls.append("paudit")
            self.events.append(("paudit", "run"))
            if self.barrier:
                self.paudit_up.set()
                await asyncio.wait_for(self.eaudit_up.wait(), 1)  # fails if sequential
            if paudit != "ok":
                raise paudit
            return self.paudit_result

        async def fake_eaudit(request, ctx, metrics):
            self.calls.append("eaudit")
            self.events.append(("eaudit", "run"))
            self.request = request
            if self.barrier:
                self.eaudit_up.set()
                await asyncio.wait_for(self.paudit_up.wait(), 1)
            if eaudit == "timeout":
                raise DeadlineExceeded("audit deadline exceeded")
            if eaudit == "error":
                raise RuntimeError("boom")
            status = Status.partial if eaudit == "partial" else Status.complete
            return (AuditResponse(request_id="req-1", status=status, warnings=[], claims=[]),
                    RunInfo(engine="eaudit", code_version="t"))

        monkeypatch.setattr(api, "_run_paudit", fake_paudit)
        monkeypatch.setattr(api, "_run_eaudit", fake_eaudit)

    def calls_of(self, name):
        return [c for c in self.calls if c == name]

    def cb(self, stage, status):
        self.events.append((stage, status))

    def seq(self, stage):
        return [s for st, s in self.events if st == stage and s != "run"]

    async def run(self, rating=FULL_RATING, paudit_result=None, cb="self"):
        return await run_evaluation(
            self.ctx, self.pack, self.transcript, self.smap, self.params, rating, paudit_result,
            self.cb if cb == "self" else cb)


def codes(out: EvaluationOutput):
    return [w.code for w in out.report.warnings]


async def test_happy_path_overlap_and_full_progress(monkeypatch):
    env = Env(monkeypatch, barrier=True)
    out = await env.run()
    assert isinstance(out, EvaluationOutput)
    for stage in STAGES:
        assert env.seq(stage) == ["started", "done"], stage
    ev = env.events
    # tips start after paudit is done; compare starts after tips and eaudit are done
    assert ev.index(("paudit", "done")) < ev.index(("tips", "started"))
    assert ev.index(("tips", "done")) < ev.index(("compare", "started"))
    assert ev.index(("eaudit", "done")) < ev.index(("compare", "started"))
    assert ev.index(("compare", "done")) < ev.index(("assemble", "started"))
    assert ev[-1] == ("assemble", "done")
    # eaudit started at t0 alongside paudit, before paudit finished
    assert ev.index(("eaudit", "started")) < ev.index(("paudit", "done"))
    assert out.report.reasons_audit.status in ("ran", "skipped")
    assert len(out.report.tips) == 3
    assert "tips_failed" not in codes(out)
    # artifacts carry the three results
    assert out.artifacts.paudit == env.paudit_result
    assert out.artifacts.eaudit is not None and out.artifacts.eaudit.status == Status.complete
    assert out.artifacts.tips is not None and len(out.artifacts.tips.valid) == 3
    assert out.report.run_info.eaudit is not None


async def test_eaudit_request_carries_profile_and_roles(monkeypatch):
    env = Env(monkeypatch)
    await env.run()
    assert env.request.profile is not None
    assert env.request.profile.suppress_concerns
    assert {s.id for s in env.request.assessment} >= {"cct", "notes"}


async def test_report_is_schema_valid_json(monkeypatch):
    env = Env(monkeypatch)
    out = await env.run()
    doc = json.loads(out.report.model_dump_json())
    assert doc["request_id"] == "req-1"
    assert doc["header"]["has_clinician_rating"] is True


async def test_raising_callback_is_ignored(monkeypatch, caplog):
    env = Env(monkeypatch)
    caplog.set_level(logging.INFO, logger="iaudit")

    def bad(stage, status):
        raise ValueError("cb exploded")

    out = await env.run(cb=bad)
    assert isinstance(out, EvaluationOutput)
    assert any("progress_cb" in r.getMessage() for r in caplog.records)
    assert not any("cb exploded" in r.getMessage() for r in caplog.records)  # no free text


async def test_no_callback_ok(monkeypatch):
    env = Env(monkeypatch)
    assert isinstance(await env.run(cb=None), EvaluationOutput)


async def test_eaudit_timeout_gives_partial(monkeypatch):
    env = Env(monkeypatch, eaudit="timeout")
    out = await env.run()
    assert out.report.reasons_audit.status == "partial"
    assert "reasons_audit_partial" in codes(out)
    assert out.report.tips
    assert env.seq("eaudit") == ["started", "failed"]
    assert out.artifacts.eaudit is None


async def test_eaudit_partial_response_gives_partial(monkeypatch):
    env = Env(monkeypatch, eaudit="partial")
    out = await env.run()
    assert out.report.reasons_audit.status == "partial"
    assert "reasons_audit_partial" in codes(out)
    assert env.seq("eaudit") == ["started", "done"]
    assert out.artifacts.eaudit is not None


async def test_eaudit_error_gives_failed(monkeypatch):
    env = Env(monkeypatch, eaudit="error")
    out = await env.run()
    assert out.report.reasons_audit.status == "failed"
    assert out.report.reasons_audit.items == []
    assert "reasons_audit_failed" in codes(out)
    assert env.seq("eaudit") == ["started", "failed"]
    assert out.report.tips  # report still ships with tips
    assert env.seq("assemble") == ["started", "done"]


async def test_tips_error_gives_tips_failed(monkeypatch):
    env = Env(monkeypatch, tips=[LLMBadOutput("x"), LLMBadOutput("y")])
    out = await env.run()
    assert out.report.tips == []
    assert "tips_failed" in codes(out)
    assert env.seq("tips") == ["started", "failed"]
    assert out.report.reasons_audit.status != "failed"
    assert env.seq("assemble") == ["started", "done"]


async def test_paudit_failure_raises_and_builds_no_report(monkeypatch):
    env = Env(monkeypatch, paudit=AllRunsFailed("all runs failed"), barrier=False)

    def no_report(**kw):
        raise AssertionError("build_report must not run")

    monkeypatch.setattr(api, "build_report", no_report)
    with pytest.raises(AllRunsFailed):
        await env.run()
    assert env.seq("paudit") == ["started", "failed"]
    assert "tips" not in env.calls  # tips never started
    assert env.seq("tips") == [] and env.seq("compare") == [] and env.seq("assemble") == []
    assert env.seq("eaudit")[-1] in ("done", "failed")  # in-flight reasons audit is wound down


async def test_paudit_failure_cancels_inflight_eaudit(monkeypatch):
    env = Env(monkeypatch, paudit=RuntimeError("boom"))
    slow = asyncio.Event()

    async def slow_eaudit(request, ctx, metrics):
        await slow.wait()  # never finishes on its own

    monkeypatch.setattr(api, "_run_eaudit", slow_eaudit)
    with pytest.raises(RuntimeError):
        await asyncio.wait_for(env.run(), 2)
    assert env.seq("eaudit") == ["started", "failed"]


async def test_no_rating_path(monkeypatch):
    env = Env(monkeypatch)
    out = await env.run(rating=None)
    assert "eaudit" not in env.calls
    assert env.seq("eaudit") == ["started", "done"]  # not applicable: done at once
    assert out.report.reasons_audit.status == "skipped"
    assert out.report.header.has_clinician_rating is False
    assert out.report.tips
    assert out.artifacts.eaudit is None
    for stage in STAGES:
        assert env.seq(stage) == ["started", "done"], stage


async def test_supplied_paudit_skips_paudit_but_reasons_audit_still_runs(monkeypatch):
    env = Env(monkeypatch, barrier=False)
    out = await env.run(paudit_result=env.paudit_result)
    assert "paudit" not in env.calls
    assert env.seq("paudit") == ["started", "done"]
    assert "eaudit" in env.calls and "tips" in env.calls
    assert out.artifacts.paudit == env.paudit_result
    assert out.report.tips
    for stage in STAGES:
        assert env.seq(stage) == ["started", "done"], stage


async def test_empty_card_is_treated_as_no_rating(monkeypatch):
    env = Env(monkeypatch)
    out = await env.run(rating={"globals": {}, "counts": {}, "notes": None})
    assert "eaudit" not in env.calls
    assert out.report.reasons_audit.status == "skipped"
