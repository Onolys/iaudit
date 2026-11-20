"""SP09 R2/D5/AC1: the real `Evaluation` adapter is one call into `run_evaluation`.
Unit tests stub `run_evaluation`, the pack loader and the LLM client; no live calls."""

import re
import time
from pathlib import Path
from types import SimpleNamespace

import pytest
from onolys_core.engine import RunContext
from onolys_core.errors import InputError
from onolys_core.transcript import Transcript

from onolys_api.adapters import real
from onolys_api.adapters.base import EvaluationOutput
from onolys_api.adapters.real import PACK_REF, RealEvaluation

pytestmark = pytest.mark.unit

PARAMS = {
    "change_goal": "cut back",
    "coded_span": {"from_s": 0, "to_s": 60},
    "language": "en",
    "n_runs": 3,
    "preset": "default",
    "code_version": "abc123",
    "stub_title": "ignored",
}
SPEAKERS = {"subject": "A"}
PACK = object()


class Engine:
    def __init__(self) -> None:
        self.calls: list[tuple] = []

    async def __call__(self, *args, **kw):
        self.calls.append((args, kw))
        return SimpleNamespace(
            report=SimpleNamespace(model_dump_json=lambda: '{"schema_version": "1"}'),
            artifacts=SimpleNamespace(model_dump_json=lambda: '{"paudit": {"x": 1}}'),
        )


def make(engine: Engine, llm=None, loads: list | None = None) -> RealEvaluation:
    def loader(ref):
        if loads is not None:
            loads.append(ref)
        return PACK

    return RealEvaluation(
        run_evaluation=engine, pack_loader=loader, llm_factory=lambda routes: llm or "llm"
    )


def ctx() -> RunContext:
    return RunContext(llm=None, metrics=None, request_id="req-9", deadline=time.monotonic() + 900)


def transcript() -> Transcript:
    return Transcript(language="en", turns=[], duration_ms=0)


async def test_one_call_with_exact_params_and_pack():
    engine, loads = Engine(), []
    rating = {"globals": {}}
    cb = lambda stage, status: None  # noqa: E731
    out = await make(engine, loads=loads).run(
        ctx(), None, transcript(), SPEAKERS, PARAMS, rating, cb
    )
    assert len(engine.calls) == 1
    (args, kw) = engine.calls[0]
    c, pack, tr, speakers, params, got_rating, paudit_result, got_cb = args
    assert loads == [PACK_REF] == ["miti@4.2.1"]
    assert pack is PACK and speakers == SPEAKERS and got_rating is rating
    assert paudit_result is None and got_cb is cb and kw == {}
    assert params == {k: v for k, v in PARAMS.items() if k != "stub_title"}
    assert c.request_id == "req-9" and c.llm == "llm" and c.metrics is not None
    assert isinstance(out, EvaluationOutput)
    assert out.report == {"schema_version": "1"} and out.artifacts == {"paudit": {"x": 1}}


async def test_no_rating_passes_none():
    engine = Engine()
    await make(engine).run(ctx(), None, transcript(), SPEAKERS, PARAMS, None)
    assert engine.calls[0][0][5] is None
    assert engine.calls[0][0][7] is None  # no progress_cb given


async def test_deadline_is_capped_at_eight_minutes():
    engine = Engine()
    before = time.monotonic()
    await make(engine).run(ctx(), None, transcript(), SPEAKERS, PARAMS, None)
    deadline = engine.calls[0][0][0].deadline
    assert before + 470 < deadline <= time.monotonic() + 480


async def test_shorter_ctx_deadline_wins():
    engine = Engine()
    c = RunContext(llm=None, metrics=None, request_id="r", deadline=time.monotonic() + 60)
    await make(engine).run(c, None, transcript(), SPEAKERS, PARAMS, None)
    assert engine.calls[0][0][0].deadline <= time.monotonic() + 60


async def test_unknown_preset_is_input_error_and_no_engine_call():
    engine = Engine()
    ev = RealEvaluation(run_evaluation=engine, pack_loader=lambda ref: PACK)  # real resolve
    with pytest.raises(InputError):
        await ev.run(
            ctx(), None, transcript(), SPEAKERS, {**PARAMS, "preset": "no-such-preset"}, None
        )
    assert engine.calls == []


async def test_default_llm_factory_builds_litellm_client_from_routes():
    from onolys_core.llm import LiteLLMClient

    engine = Engine()
    ev = RealEvaluation(run_evaluation=engine, pack_loader=lambda ref: PACK)
    await ev.run(ctx(), None, transcript(), SPEAKERS, PARAMS, None)
    assert isinstance(engine.calls[0][0][0].llm, LiteLLMClient)


def test_adapter_names_no_model_or_provider():
    src = Path(real.__file__).read_text().lower()
    code = "\n".join(line for line in src.splitlines() if not line.lstrip().startswith("#"))
    # strip the STT section's registry keys (provider keys are data, SP09 T2); check Evaluation part
    part = code[code.index("class realevaluation") :]
    assert not re.search(
        r"claude|anthropic|gemini|gpt|openai|vertex|sonnet|haiku|opus|litellm_id", part
    )
