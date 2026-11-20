import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
from onolys_core.engine import RunContext
from onolys_core.errors import ConfigError
from onolys_core.stt import AudioRef, SttParams, Word
from onolys_core.stt.base import words_to_turns
from onolys_core.stt.fixture import FixtureStt, uri_hash
from onolys_core.transcript import Transcript

from onolys_api.adapters import AdapterError, FakeEvaluation, FakeStt, build_adapters
from onolys_api.adapters import fake as f
from onolys_api.config import Settings

pytestmark = pytest.mark.unit
ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).parent / "schemas"


def _schema(real: str, local: str) -> dict:
    p = ROOT / real
    return json.loads((p if p.exists() else HERE / local).read_text())


REPORT = Draft202012Validator(
    _schema("engines/evaluation/schemas/report.schema.json", "report.local.schema.json")
)
PAUDIT = Draft202012Validator(
    _schema("engines/paudit/schemas/paudit-result.schema.json", "paudit-result.local.schema.json")
)
AUDIO = AudioRef(uri="gs://b/u/s/audio/canonical.flac", mime="audio/flac", duration_ms=1000)
CTX = RunContext(llm=None, metrics=None, request_id="req-1")
PARAMS = {"change_goal": "cut back", "coded_span": {"from_s": 0, "to_s": 600}, "language": "en",
          "n_runs": 2, "preset": "default", "code_version": "abc"}  # fmt: skip
RATING = {"final": True}


def sparams(title: str | None = None) -> SttParams:
    opts = {f.STUB_TITLE_KEY: title} if title else {}
    return SttParams(provider="fake", model="fake", options=opts)


async def transcribe(adapter: FakeStt, title: str | None = None) -> Transcript | None:
    h = await adapter.start(AUDIO, sparams(title))
    return await adapter.poll(h)


async def evaluate(title: str = "", rating=RATING, events=None, adapter=None):
    t = await transcribe(FakeStt())
    cb = (lambda s, st: events.append((s, st))) if events is not None else None
    ev = adapter or FakeEvaluation()
    return await ev.run(CTX, None, t, {"subject": "S1"}, {**PARAMS, f.STUB_TITLE_KEY: title},
                        rating, cb)  # fmt: skip


# ---- Stt ----


async def test_stt_deterministic_and_counts_starts():
    a, b = FakeStt(), FakeStt()
    assert (await transcribe(a)) == (await transcribe(b))
    assert (await transcribe(a)).model_dump() == (await transcribe(b)).model_dump()
    assert a.start_calls == 2 and len(a.started) == 2
    h1 = await a.start(AUDIO, sparams())
    assert h1 == f"fake-stt:{h1.split(':')[1]}:3"  # handle is JSON-serialisable and stable


async def test_stt_ok_shape():
    t = await transcribe(FakeStt())
    words = sum(len(x.text.split()) for x in t.turns)
    assert {x.speaker for x in t.turns} == {"S1", "S2"} and words >= 50
    assert t.stt_run.provider == "fake"


async def test_stt_poll_not_ready_then_ready_without_resubmit():
    a = FakeStt(polls_before_ready=2)
    h = await a.start(AUDIO, sparams())
    assert await a.poll(h) is None and await a.poll(h) is None
    assert await a.poll(h) is not None
    assert a.start_calls == 1


async def test_stt_no_speech():
    assert (await transcribe(FakeStt(), f"x {f.FAIL_NO_SPEECH}")).turns == []


async def test_stt_one_speaker():
    t = await transcribe(FakeStt(), f.FAIL_SPEAKERS)
    assert {x.speaker for x in t.turns} == {"S1"}


async def test_stt_transcription_failed():
    a = FakeStt()
    h = await a.start(AUDIO, sparams(f.FAIL_TRANSCRIPTION))
    with pytest.raises(AdapterError) as e:
        await a.poll(h)
    assert e.value.code == "transcription_failed"


async def test_fixture_stt_replays_and_counts_submits():
    words = [Word(text="hi", start_ms=0, end_ms=100, speaker="A")]
    fx = FixtureStt({uri_hash(AUDIO.uri): words})
    h = await fx.start(AUDIO, sparams())
    t = await fx.poll(h)
    assert fx.submits == 1 and t.turns == words_to_turns(words)


# ---- Evaluation ----


async def test_eval_deterministic_and_schema_valid():
    a, b = await evaluate(), await evaluate()
    assert a == b
    assert not list(REPORT.iter_errors(a.report))
    assert not list(PAUDIT.iter_errors(a.artifacts["paudit"]))
    assert a.report["reasons_audit"]["status"] == "ran" and a.report["warnings"] == []
    assert a.report["header"]["stt"]["provider"] == "fake"
    t = await transcribe(FakeStt())
    texts = {x.id: x.text for x in t.turns}
    for tip in a.report["tips"]:  # quotes are real transcript substrings
        q = tip["quote"]
        assert texts[q["turn_id"]][q["start"] : q["end"]] == q["text"]


async def test_eval_no_rating_valid():
    o = await evaluate(rating=None)
    assert not list(REPORT.iter_errors(o.report))
    assert o.report["reasons_audit"]["status"] == "skipped"
    assert o.report["aggregates"]["within_one_share"] is None


async def test_progress_every_stage_started_then_terminal():
    ev: list = []
    await evaluate(events=ev)
    assert ev == [("paudit", "started"), ("eaudit", "started"), ("paudit", "done"),
                  ("eaudit", "done"), ("tips", "started"), ("tips", "done"),
                  ("compare", "started"), ("compare", "done"),
                  ("assemble", "started"), ("assemble", "done")]  # fmt: skip


async def test_inject_paudit_failed():
    ev: list = []
    with pytest.raises(AdapterError) as e:
        await evaluate(f"t {f.FAIL_PAUDIT}", events=ev)
    assert e.value.code == "paudit_failed" and ("paudit", "failed") in ev
    assert ("assemble", "started") not in ev


async def test_inject_eaudit_failed_partial_report():
    ev: list = []
    o = await evaluate(f.FAIL_EAUDIT, events=ev)
    assert not list(REPORT.iter_errors(o.report))
    assert o.report["reasons_audit"] == {"status": "failed", "items": []}
    assert {"code": "reasons_audit_failed"} in o.report["warnings"]
    assert ("eaudit", "failed") in ev and o.report["tips"]


async def test_inject_tips_failed_partial_report():
    ev: list = []
    o = await evaluate(f.FAIL_TIPS, events=ev)
    assert not list(REPORT.iter_errors(o.report))
    assert o.report["tips"] == [] and {"code": "tips_failed"} in o.report["warnings"]
    assert ("tips", "failed") in ev and o.report["reasons_audit"]["status"] == "ran"


async def test_no_progress_cb_ok():
    assert (await evaluate()).report["request_id"] == "req-1"


# ---- switch ----


def test_build_adapters_stub_and_real():
    a = build_adapters(Settings(env="test", adapters="stub"))
    assert isinstance(a.stt, FakeStt) and isinstance(a.evaluation, FakeEvaluation)
    with pytest.raises(ConfigError, match="SP09"):
        build_adapters(Settings(env="test", adapters="real"))
