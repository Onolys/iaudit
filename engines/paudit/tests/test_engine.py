import asyncio
import json
import logging
import re
import shutil

import jsonschema
import pytest
from conftest import write_pack
from onolys_core import RunContext
from onolys_core.llm import LLMBadOutput, LLMResult, MetricsCollector, Usage
from onolys_core.llm.routes import allowed_presets
from onolys_core.transcript import Transcript, Turn

import paudit.code_pass as code_pass_mod
from paudit.engine import AllRunsFailed, PauditEngine, aggregate, prompt_hashes, run
from paudit.pack import load_pack
from paudit.result import PauditResult, schema_text

pytestmark = pytest.mark.unit

T1 = "You want to walk more. What would help?"
T2 = "I would have more energy."
T3 = "You decide what fits your week."
T4 = "Okay."
PARAMS = {"speaker_map": {"subject": "A"}, "change_goal": "walk more"}


def transcript():
    return Transcript(
        language="en",
        turns=[
            Turn(id="t1", speaker="A", text=T1, start_ms=0, end_ms=1000),
            Turn(id="t2", speaker="B", text=T2, start_ms=1000, end_ms=2000),
            Turn(id="t3", speaker="A", text=T3, start_ms=2000, end_ms=3000),
            Turn(id="t4", speaker="B", text=T4, start_ms=3000, end_ms=4000),
        ],
    )


def ev(turn_id, quote):
    return {"turn_id": turn_id, "quote": quote}


def code_reply(req, run_idx=0, a_code="a", b_code="b"):
    asked = {v["volley_id"] for v in json.loads(req.user)["volleys"]}
    volleys = [
        {"volley_id": "v1", "utterances": [
            {"quote": "You want to walk more.", "code": a_code, "rationale": "r"}]},
        {"volley_id": "v2", "utterances": [{"quote": T3, "code": b_code, "rationale": "r"}]},
    ]
    return req.response_model.model_validate(
        {"volleys": [v for v in volleys if v["volley_id"] in asked]}
    )


def globals_reply(req, run_idx=0, s1=4, s2=2):
    g = lambda s, e: {"score": s, "reason": "r", "evidence": e, "poor_practice_cited": []}  # noqa: E731
    return req.response_model.model_validate(
        {"globals": {
            "g1": g(s1, [ev("t1", "What would help?"), ev("t3", "You decide what fits")]),
            "g2": g(s2, [ev("t2", "more energy")]),
        }}
    )


class FakeClient:
    """Stub client: handlers per route; run index parsed from the call_tag."""

    def __init__(self, code=code_reply, glob=globals_reply):
        self.code, self.glob, self.requests = code, glob, []

    async def complete_json(self, req, metrics=None):
        self.requests.append(req)
        run_idx = int(re.search(r":r(\d+):", req.call_tag).group(1))
        h = self.code if req.tier == "paudit_code" else self.glob
        parsed = h(req, run_idx)
        if metrics is not None:
            metrics.record(req, "fake", Usage(input_tokens=10, output_tokens=5), 0.0, 1, True)
        return LLMResult(parsed=parsed, model="fake")


def bad(req, run_idx):
    raise LLMBadOutput("truncated")


def make_pack(tmp_path, name="p"):
    return load_pack(write_pack(tmp_path / name))


def do_run(client, pack, params=None, **kw):
    return asyncio.run(run(transcript(), pack, params or PARAMS, client, **kw))


def test_n1_aggregate_equals_single_run(tmp_path):
    client = FakeClient()
    res = do_run(client, make_pack(tmp_path), request_id="req-1")
    assert isinstance(res, PauditResult)
    assert res.n_runs == 1 and len(res.results) == 1
    only = res.results[0]
    assert only.run_index == 0 and res.aggregate.representative_run == 0
    for k, v in only.counts.items():
        s = res.aggregate.counts[k]
        assert s.mean == s.min == s.max == v and s.values == [v]
    for k, gscore in only.globals.items():
        s = res.aggregate.globals[k]
        assert s.mean == s.min == s.max == gscore.score
    for k, sm in only.summaries.items():
        assert res.aggregate.summaries[k].mean == sm.value
        assert res.aggregate.summaries[k].label == sm.label
    assert res.request_id == "req-1"
    assert res.protocol.id == "demo" and res.subject_speaker == "A"
    assert res.change_goal == "walk more" and res.language == "en"
    # both routes requested, globals alongside the code pass
    assert {r.tier for r in client.requests} == {"paudit_code", "paudit_globals"}
    assert all(":r0:" in r.call_tag for r in client.requests)


def test_result_validates_against_schema(tmp_path):
    res = do_run(FakeClient(), make_pack(tmp_path))
    jsonschema.validate(json.loads(res.model_dump_json()), json.loads(schema_text()))


def test_run_info(tmp_path):
    pack = make_pack(tmp_path)
    ri = do_run(FakeClient(), pack, {**PARAMS, "preset": allowed_presets()[0]}).run_info
    assert ri.engine == "paudit" and ri.preset == allowed_presets()[0] and ri.n_runs == 1
    assert ri.pack.id == "demo" and ri.pack.hash == pack.pack_hash
    assert set(ri.routes) == {"paudit_code", "paudit_globals"}
    assert ri.usage.calls == 2 and ri.usage.input_tokens == 20
    assert ri.code_version
    assert {"code_system.md", "code_fewshot.json", "globals_system.md",
            "globals_fewshot.json"} <= set(ri.prompt_hashes)


def test_prompt_hashes_change_with_pack_prompt(tmp_path):
    pack = make_pack(tmp_path, "p1")
    shutil.copytree(pack.root, tmp_path / "p2")
    (tmp_path / "p2" / "prompts" / "code_system.md").write_text("doctored")
    h1, h2 = prompt_hashes(pack), prompt_hashes(load_pack(tmp_path / "p2"))
    assert h1 != h2
    assert [k for k in h1 if h1[k] != h2[k]] == ["code_system.md"]


def test_prompt_hashes_change_with_engine_template(tmp_path, monkeypatch):
    pack = make_pack(tmp_path)
    before = prompt_hashes(pack)
    monkeypatch.setattr(code_pass_mod, "_OUTPUT_FORMAT", "changed instructions")
    after = prompt_hashes(pack)
    assert before != after
    assert {k for k in before if before[k] != after[k]} == {"engine:code_output_format"}


def test_logs_hold_no_transcript_text(tmp_path, caplog):
    caplog.set_level(logging.DEBUG)
    do_run(FakeClient(), make_pack(tmp_path), request_id="req-1")
    with pytest.raises(AllRunsFailed):
        do_run(FakeClient(code=bad), make_pack(tmp_path), request_id="req-2")
    assert caplog.records, "engine should log something"
    for needle in (T1, T2, T3, "walk more", "What would help", "more energy"):
        assert needle not in caplog.text


def test_n2_one_failed_run_excluded(tmp_path):
    def code(req, run_idx):
        if run_idx == 1:
            raise LLMBadOutput("truncated")
        return code_reply(req, run_idx)

    res = do_run(FakeClient(code=code), make_pack(tmp_path), {**PARAMS, "n_runs": 2})
    assert [r.run_index for r in res.results] == [0]
    assert res.n_runs == 2 and res.run_info.n_runs == 2
    w = [w for w in res.warnings if w.code == "run_failed"]
    assert len(w) == 1 and "1" in (w[0].detail or "")
    assert res.aggregate.representative_run == 0
    assert res.aggregate.counts["a"].values == [1]
    # engine contract: still validates
    PauditResult.model_validate_json(res.model_dump_json())


def test_n2_first_run_failed_keeps_original_index(tmp_path):
    def code(req, run_idx):
        if run_idx == 0:
            raise LLMBadOutput("truncated")
        return code_reply(req, run_idx)

    res = do_run(FakeClient(code=code), make_pack(tmp_path), {**PARAMS, "n_runs": 2})
    assert [r.run_index for r in res.results] == [1]
    assert res.aggregate.representative_run == 1


def test_all_runs_failed_is_error(tmp_path):
    with pytest.raises(AllRunsFailed) as e:
        do_run(FakeClient(glob=bad), make_pack(tmp_path), {**PARAMS, "n_runs": 2})
    assert e.value.code == "run_failed"


def test_n2_aggregate_values(tmp_path):
    def code(req, run_idx):
        return code_reply(req, run_idx, a_code="a", b_code="a" if run_idx == 1 else "b")

    res = do_run(FakeClient(code=code), make_pack(tmp_path), {**PARAMS, "n_runs": 2})
    assert res.aggregate.counts["a"].values == [1, 2]
    assert res.aggregate.counts["a"].mean == 1.5
    assert (res.aggregate.counts["a"].min, res.aggregate.counts["a"].max) == (1, 2)
    assert res.aggregate.representative_run == 0  # tie -> lowest index


def _fake_runs(counts_a, globals_g1):
    from paudit.result import GlobalScore, RunResult

    out = []
    for i, (a, g1) in enumerate(zip(counts_a, globals_g1, strict=True)):
        out.append(RunResult(
            run_index=i, instances=[], counts={"a": a},
            globals={"g1": GlobalScore(score=g1, source="model", raw_score=g1, reason="r",
                                       evidence=[])},
            summaries={}, warnings=[]))
    return out


def test_representative_run_closest_to_mean(tmp_path):
    pack = make_pack(tmp_path)
    runs = _fake_runs([0, 4, 5], [3, 3, 3])  # mean a = 3 -> run 1 (|4-3|) beats run 2, 0
    assert aggregate(pack, runs).representative_run == 1


def test_representative_run_uses_globals_too(tmp_path):
    pack = make_pack(tmp_path)
    runs = _fake_runs([2, 2, 2], [1, 3, 5])  # mean g1 = 3
    assert aggregate(pack, runs).representative_run == 1


def test_representative_run_tie_lowest(tmp_path):
    pack = make_pack(tmp_path)
    assert aggregate(pack, _fake_runs([1, 3], [3, 3])).representative_run == 0


def test_runs_after_first_wait_for_warm_call(tmp_path):
    client = FakeClient()
    do_run(client, make_pack(tmp_path), {**PARAMS, "n_runs": 2})
    tags = [r.call_tag for r in client.requests if r.tier == "paudit_code"]
    assert tags[0].startswith("paudit_code:r0:")
    assert {t.split(":")[1] for t in tags} == {"r0", "r1"}


def test_param_overrides_reach_request(tmp_path):
    client = FakeClient()
    do_run(client, make_pack(tmp_path), {**PARAMS, "volleys_per_call": 1, "code_max_tokens": 123,
                                         "globals_max_tokens": 77})
    code = [r for r in client.requests if r.tier == "paudit_code"]
    assert len(code) == 2 and {r.max_tokens for r in code} == {123}
    assert [r.max_tokens for r in client.requests if r.tier == "paudit_globals"] == [77]


def test_language_warning(tmp_path):
    res = do_run(FakeClient(), make_pack(tmp_path), {**PARAMS, "language": "de"})
    assert res.language == "de"
    assert any(w.code == "language_not_validated" and w.severity == "info" for w in res.warnings)


def test_engine_class_via_ctx(tmp_path):
    pack = make_pack(tmp_path)
    metrics = MetricsCollector()
    ctx = RunContext(llm=FakeClient(), metrics=metrics, request_id="req-9")
    out = asyncio.run(PauditEngine().run(transcript(), pack.ref(), PARAMS, ctx))
    assert PauditEngine.name == "paudit"
    assert isinstance(out.result, PauditResult) and out.result.request_id == "req-9"
    assert out.run_info == out.result.run_info
    assert out.run_info.usage.calls == 2 and len(metrics.records) == 2


def test_engine_class_needs_pack():
    from onolys_core import InputError

    ctx = RunContext(llm=FakeClient(), metrics=None, request_id="r")
    with pytest.raises(InputError):
        asyncio.run(PauditEngine().run(transcript(), None, PARAMS, ctx))
