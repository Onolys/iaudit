import json
import subprocess
import sys
from pathlib import Path

import pytest
from pydantic import BaseModel, ValidationError

from onolys_core import (
    AudioRef,
    Engine,
    EngineResult,
    InputError,
    OnolysError,
    PackError,
    PackRef,
    RunContext,
    Span,
    SttAdapter,
    SttParams,
    SttRun,
    Transcript,
    Turn,
    Word,
)
from onolys_core.run_info import RunInfo

pytestmark = pytest.mark.unit


def _run() -> SttRun:
    return SttRun(
        provider="google", model="chirp_3", language_requested="auto", adapter_version="1"
    )


def test_turn_defaults_and_required():
    t = Turn(id="t1", text="hi")
    assert t.speaker is None and t.start_ms is None and t.end_ms is None
    assert t.role is None and t.language is None
    with pytest.raises(ValidationError):
        Turn(id="t1")  # type: ignore[call-arg]


def test_transcript_roundtrip():
    tr = Transcript(
        turns=[Turn(id="t1", text="hi", start_ms=0, end_ms=5)],
        language="en-US",
        duration_ms=5,
        stt_run=_run(),
    )
    assert Transcript.model_validate(json.loads(tr.model_dump_json())) == tr
    assert Transcript(turns=[]).stt_run is None


def test_span_requires_all_fields():
    assert Span(turn_id="t1", start=0, end=3).end == 3
    with pytest.raises(ValidationError):
        Span(turn_id="t1", start=0)  # type: ignore[call-arg]


def test_stt_params_defaults():
    p = SttParams(provider="google", model="chirp_3")
    assert (p.language, p.diarization, p.speakers_min, p.speakers_max, p.options) == (
        "auto",
        True,
        2,
        2,
        {},
    )
    with pytest.raises(ValidationError):
        SttParams(provider="google")  # type: ignore[call-arg]


def test_audio_ref_callable_and_defaults():
    a = AudioRef(uri="gs://b/x.flac", mime="audio/flac")
    assert a.local_path_fn is None and a.duration_ms is None
    b = AudioRef(uri="u", mime="audio/flac", local_path_fn=lambda: Path("/x"), duration_ms=10)
    assert b.local_path_fn() == Path("/x")


def test_word_and_sttrun():
    w = Word(text="a", start_ms=0, end_ms=1)
    assert w.speaker is None
    with pytest.raises(ValidationError):
        Word(text="a", start_ms=0)  # type: ignore[call-arg]
    r = _run()
    assert r.location is None and r.language_detected is None
    with pytest.raises(ValidationError):
        SttRun(provider="p", model="m")  # type: ignore[call-arg]


async def test_stt_adapter_protocol_usable():
    class Fake:
        async def start(self, audio, params):
            return "h1"

        async def poll(self, handle):
            return Transcript(turns=[])

    a: SttAdapter = Fake()
    assert await a.start(AudioRef(uri="u", mime="m"), SttParams(provider="p", model="m")) == "h1"
    assert (await a.poll("h1")) == Transcript(turns=[])


class _Out(BaseModel):
    x: int


async def test_engine_protocol_and_result():
    class E:
        name = "eaudit"

        async def run(self, transcript, pack, params, ctx):
            return EngineResult(
                result=_Out(x=1), run_info=RunInfo(engine="eaudit", code_version="x")
            )

    e: Engine = E()
    ctx = RunContext(llm=object(), metrics=object(), request_id="r1")
    assert ctx.deadline is None
    res = await e.run(Transcript(turns=[]), PackRef(id="p", version="1", path="/p"), {}, ctx)
    assert res.result == _Out(x=1)
    with pytest.raises(ValidationError):
        EngineResult(result=_Out(x=1), run_info=_Out(x=2))  # not a RunInfo
    with pytest.raises(ValidationError):
        EngineResult(result=_Out(x=1))  # type: ignore[call-arg]
    with pytest.raises(ValidationError):
        PackRef(id="p")  # type: ignore[call-arg]


def test_error_hierarchy():
    assert issubclass(InputError, OnolysError) and issubclass(PackError, OnolysError)
    assert not issubclass(InputError, PackError)
    with pytest.raises(OnolysError):
        raise InputError("bad")


def test_core_imports_no_eaudit_paudit_api():
    """Boundary: importing core (and walking its source) pulls in no sibling packages."""
    forbidden = ("eaudit", "paudit", "api", "iaudit_eval")
    code = (
        "import sys, onolys_core, onolys_core.stt, onolys_core.engine;"
        f"bad=[m for m in sys.modules if m.split('.')[0] in {forbidden!r}];"
        "print(bad)"
    )
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True)
    assert out.stdout.strip() == "[]"

    src = Path(__file__).resolve().parents[1] / "src" / "onolys_core"
    import ast

    for f in src.rglob("*.py"):
        for node in ast.walk(ast.parse(f.read_text())):
            names = []
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                names = [node.module]
            for n in names:
                assert n.split(".")[0] not in forbidden, f"{f} imports {n}"
