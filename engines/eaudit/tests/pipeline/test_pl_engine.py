"""EauditEngine: thin wrapper over the pipeline (core PRD R6, R10, AC13)."""

import json

import pytest
from onolys_core import RunContext, Transcript
from onolys_core.llm import MetricsCollector
from onolys_core.run_info import RunInfo
from pl_scripted import Scripted

from eaudit.config import Settings
from eaudit.engine import EauditEngine
from eaudit.models import AuditRequest
from eaudit.pipeline.full import FullPipeline

PROFILE = {"suppress_concerns": ["opinion_as_fact"], "context_note": "self-rating"}
SECRET = "sk-ant-SECRETVALUE"


def _inputs(s: Scripted):
    req = s.request
    transcript = Transcript.from_eaudit_turns(req["transcript"])
    return req, transcript, {"assessment": req["assessment"], "preset": "default"}


async def _direct(make_ctx, s: Scripted):
    req, _, _ = _inputs(s)
    ctx = make_ctx(llm=s, request_id=req["request_id"])
    return await FullPipeline().run(AuditRequest.model_validate(req), ctx)


@pytest.mark.parametrize("profile", [None, PROFILE])
async def test_wrapper_result_equals_direct_pipeline(make_ctx, profile):
    direct = await _direct(make_ctx, Scripted(None))
    s = Scripted(None)
    req, transcript, params = _inputs(s)
    if profile is not None:
        params["profile"] = profile
    rctx = RunContext(llm=s, metrics=MetricsCollector(), request_id=req["request_id"])
    out = await EauditEngine(Settings(llm_mode="stub")).run(transcript, None, params, rctx)
    assert out.result.to_json() == direct.to_json()
    assert len(out.result.claims) == 11


async def test_profile_reaches_the_request(monkeypatch):
    seen = {}

    class Spy:
        async def run(self, req, ctx):
            seen["profile"] = req.profile
            from eaudit.models import AuditResponse, Status

            return AuditResponse(
                request_id=req.request_id, status=Status.complete, warnings=[], claims=[]
            )

    s = Scripted(None)
    req, transcript, params = _inputs(s)
    rctx = RunContext(llm=s, metrics=MetricsCollector(), request_id="r")
    eng = EauditEngine(Settings(llm_mode="stub"), pipeline=Spy())
    await eng.run(transcript, None, {**params, "profile": PROFILE}, rctx)
    assert seen["profile"].model_dump(mode="json") == PROFILE
    await eng.run(transcript, None, params, rctx)
    assert seen["profile"] is None


async def test_run_info_for_an_eaudit_run(monkeypatch):
    monkeypatch.setenv("GIT_SHA", "deadbeef")
    monkeypatch.setenv("GEMINI_API_KEY", SECRET)
    s = Scripted(None)
    req, transcript, params = _inputs(s)
    metrics = MetricsCollector()
    rctx = RunContext(llm=s, metrics=metrics, request_id=req["request_id"])
    out = await EauditEngine(Settings(llm_mode="stub")).run(transcript, None, params, rctx)
    ri = out.run_info
    assert isinstance(ri, RunInfo)
    assert ri.engine == "eaudit" and ri.code_version == "deadbeef" and ri.preset == "default"
    assert set(ri.routes) == {"cheap", "mid", "strong"}
    for f in ri.routes.values():
        assert f.provider == "gemini" and f.temperature_effective is None
        assert len(f.params_hash) == 16
    assert set(ri.prompt_hashes) >= {"atomize", "link", "check", "prep"}
    assert ri.stt is None and ri.pack is None and ri.n_runs == 1
    blob = ri.model_dump_json()
    assert SECRET not in blob
    texts = [t["text"] for t in req["transcript"]] + [x["text"] for x in req["assessment"]]
    assert not any(t[:30] in blob for t in texts)
    assert json.loads(blob)["usage"]["calls"] == metrics.snapshot()["calls"]
