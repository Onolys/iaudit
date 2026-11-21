import asyncio
import io
import logging
import pathlib
import sys
from datetime import timedelta
from types import ModuleType
from types import SimpleNamespace as NS

import pytest
import yaml

from onolys_core.errors import ConfigError, InputError
from onolys_core.safe_log import log
from onolys_core.voice import (
    AudioOut,
    Closed,
    GoAway,
    Interrupted,
    ResumptionHandle,
    TurnComplete,
    VoiceParams,
    VoiceProviderError,
)
from onolys_core.voice.fixture import FixtureVoice, silence_pcm24k, tone_pcm24k
from onolys_core.voice.gemini_live_vertex import GeminiLiveVertex
from onolys_core.voice.select import (
    allowed_voices,
    load_voice_config,
    locate_config_file,
    select_voice,
    validate_voice_config,
)

pytestmark = pytest.mark.unit

REPO = pathlib.Path(__file__).resolve().parents[3]
SECRET = "SECRET-PROMPT-TEXT-xyz"


def params(**kw) -> VoiceParams:
    base = dict(provider="p", model="m", voice="Kore", system_prompt=SECRET)
    return VoiceParams(**{**base, **kw})


# ---- config -------------------------------------------------------------------------------


def test_packaged_default_and_location_precedence(tmp_path, monkeypatch):
    monkeypatch.delenv("ROUTES_FILE", raising=False)
    monkeypatch.delenv("VOICE_PROVIDERS_FILE", raising=False)
    assert locate_config_file().name == "voice_providers.default.yaml"
    cfg = load_voice_config()
    assert cfg["default"] == "gemini_live" and len(cfg["voices"]) == 30
    (tmp_path / "routes.yaml").write_text("{}")
    f = tmp_path / "voice_providers.yaml"
    f.write_text("providers: {x: {provider: px, model: mx, voice: V}}\ndefault: x\nvoices: [V]\n")
    monkeypatch.setenv("ROUTES_FILE", str(tmp_path / "routes.yaml"))
    assert locate_config_file() == f
    assert select_voice().provider == "px"
    other = tmp_path / "other.yaml"
    monkeypatch.setenv("VOICE_PROVIDERS_FILE", str(other))
    assert locate_config_file() == other


@pytest.mark.parametrize("env", ["staging", "prod"])
def test_deployed_config_files_valid(env):
    cfg = load_voice_config(REPO / "config" / env / "voice_providers.yaml")
    entry = cfg["providers"][cfg["default"]]
    assert entry["model"] == "gemini-3.8-live" and entry["voice"] == "Kore"
    assert entry["options"]["location"] == "us-central1"
    assert len(set(cfg["voices"])) == 30


def good():
    return yaml.safe_load(
        "providers: {k: {provider: p, model: m, voice: A, options: {a: 1}}}\n"
        "default: k\nvoices: [A, B]\n"
    )


def test_select_voice_maps_fields_and_validates_voice():
    p = select_voice(None, "B", "es-ES", system_prompt="sp", resumption_handle="h", config=good())
    assert (p.provider, p.model, p.voice, p.language) == ("p", "m", "B", "es-ES")
    assert p.options == {"a": 1} and p.resumption_handle == "h" and p.system_prompt == "sp"
    assert select_voice(config=good()).voice == "A"  # provider default voice
    assert select_voice(config=good()).language == "en-US"
    with pytest.raises(InputError):
        select_voice(None, "Nope", config=good())
    with pytest.raises(InputError):
        select_voice("missing", config=good())
    assert allowed_voices(good()) == ["A", "B"]


def test_validation_errors():
    for mutate in (
        lambda c: c.pop("providers"),
        lambda c: c.update(providers={}),
        lambda c: c.pop("voices"),
        lambda c: c.update(voices=[]),
        lambda c: c.update(default="nope"),
        lambda c: c["providers"]["k"].pop("model"),
        lambda c: c["providers"]["k"].update(voice="Z"),
        lambda c: c["providers"]["k"].update(options=[1]),
    ):
        cfg = good()
        mutate(cfg)
        with pytest.raises(ConfigError):
            validate_voice_config(cfg)


def test_params_repr_hides_prompt():
    assert SECRET not in repr(params()) and SECRET not in str(params())


# ---- fixture ------------------------------------------------------------------------------


def test_tone_is_deterministic_pcm16():
    a = tone_pcm24k(100)
    assert a == tone_pcm24k(100) and len(a) == 2400 * 2 and a != silence_pcm24k(100)
    assert silence_pcm24k(50) == b"\x00" * 2400


async def collect(session):
    return [e async for e in session.events()]


async def test_fixture_default_sequence_and_close():
    fx = FixtureVoice()
    s = await fx.open(params())
    got = []

    async def run():
        async for e in s.events():
            got.append(e)

    task = asyncio.create_task(run())
    await asyncio.sleep(0.01)
    assert [type(e) for e in got] == [AudioOut, AudioOut, TurnComplete, ResumptionHandle]
    await s.send_audio(b"\x01\x02")
    await s.close()
    await task
    assert got[-1] == Closed("closed") and s.sent == [b"\x01\x02"]
    assert fx.opened[0].voice == "Kore"
    with pytest.raises(VoiceProviderError):
        await s.send_audio(b"x")


async def test_fixture_scripted_events_end_on_closed():
    script = [Interrupted(), GoAway(5.0), ResumptionHandle("h2"), Closed("dropped")]
    s = await FixtureVoice(script).open(params())
    assert await collect(s) == script


async def test_fixture_failure_injection():
    with pytest.raises(VoiceProviderError):
        await FixtureVoice(fail_open=True).open(params())
    s = await FixtureVoice(fail_send_after=1).open(params())
    await s.send_audio(b"a")
    with pytest.raises(VoiceProviderError):
        await s.send_audio(b"b")
    s = await FixtureVoice(fail_events_after=1).open(params())
    it = s.events()
    assert isinstance(await anext(it), AudioOut)
    with pytest.raises(VoiceProviderError):
        await anext(it)


# ---- gemini adapter against a faked SDK ---------------------------------------------------


class _Cfg:
    """Stand-in for a google.genai.types model: keyword args become attributes, rest None."""

    def __init__(self, **kw):
        self.__dict__.update(kw)

    def __getattr__(self, name):
        if name.startswith("__"):
            raise AttributeError(name)
        return None


@pytest.fixture(autouse=True)
def fake_genai_types(monkeypatch):
    """The core CI job installs onolys-core without the `voice-gemini` extra: fake the SDK."""
    names = (
        "SpeechConfig VoiceConfig PrebuiltVoiceConfig SessionResumptionConfig "
        "ContextWindowCompressionConfig SlidingWindow LiveConnectConfig Blob"
    ).split()
    types = ModuleType("google.genai.types")
    for n in names:
        setattr(types, n, type(n, (_Cfg,), {}))
    genai = ModuleType("google.genai")
    genai.types = types
    monkeypatch.setitem(sys.modules, "google.genai", genai)
    monkeypatch.setitem(sys.modules, "google.genai.types", types)


class FakeLive:
    def __init__(self, batches, connect_error=None):
        self.batches = batches
        self.connect_error = connect_error
        self.connect_kwargs = None
        self.sent = []
        self.exited = 0
        self.client_options = None

    # client side
    def factory(self, options):
        self.client_options = options
        return NS(aio=NS(live=NS(connect=self.connect)))

    def connect(self, **kw):
        self.connect_kwargs = kw
        return self

    async def __aenter__(self):
        if self.connect_error:
            raise self.connect_error
        return self

    async def __aexit__(self, *a):
        self.exited += 1

    # session side
    async def send_realtime_input(self, **kw):
        self.sent.append(kw)

    async def receive(self):
        if not self.batches:
            raise ConnectionError("gone")
        for m in self.batches.pop(0):
            yield m


def msg(**kw):
    base = dict(
        server_content=None, go_away=None, session_resumption_update=None, usage_metadata=None
    )
    return NS(**{**base, **kw})


def audio(b):
    part = NS(inline_data=NS(data=b))
    return msg(
        server_content=NS(
            model_turn=NS(parts=[part, NS(inline_data=None)]), interrupted=None, turn_complete=None
        )
    )


def flag(**kw):
    return msg(
        server_content=NS(model_turn=None, interrupted=kw.get("i"), turn_complete=kw.get("t"))
    )


async def test_gemini_params_mapping_default():
    fake = FakeLive([])
    s = await GeminiLiveVertex(fake.factory).open(
        params(model="gemini-3.8-live", voice="Puck", language="de-DE", options={"location": "eu"})
    )
    kw = fake.connect_kwargs
    cfg = kw["config"]
    assert kw["model"] == "gemini-3.8-live" and fake.client_options == {"location": "eu"}
    assert cfg.system_instruction == SECRET
    assert list(cfg.response_modalities) == ["AUDIO"] or [
        str(getattr(m, "value", m)) for m in cfg.response_modalities
    ] == ["AUDIO"]
    sp = cfg.speech_config
    assert sp.voice_config.prebuilt_voice_config.voice_name == "Puck"
    assert sp.language_code == "de-DE"
    assert cfg.session_resumption is not None and cfg.session_resumption.handle is None
    assert cfg.context_window_compression is None
    await s.close()
    await s.close()
    assert fake.exited == 1


async def test_gemini_resumption_handle_and_compression_option():
    fake = FakeLive([])
    p = params(resumption_handle="H1", options={"context_window_compression": True})
    await GeminiLiveVertex(fake.factory).open(p)
    cfg = fake.connect_kwargs["config"]
    assert cfg.session_resumption.handle == "H1"
    assert cfg.context_window_compression.sliding_window is not None


async def test_gemini_send_audio_blob():
    fake = FakeLive([])
    s = await GeminiLiveVertex(fake.factory).open(params())
    await s.send_audio(b"\x00\x01")
    blob = fake.sent[0]["audio"]
    assert blob.data == b"\x00\x01" and blob.mime_type == "audio/pcm;rate=16000"


async def test_gemini_event_mapping_handle_goaway_and_drop():
    batches = [
        [
            audio(b"AA"),
            msg(session_resumption_update=NS(new_handle="H2", resumable=True)),
            msg(session_resumption_update=NS(new_handle=None, resumable=False)),
            msg(session_resumption_update=NS(new_handle="Hx", resumable=False)),
            flag(i=True),
            flag(t=True),
        ],
        [msg(go_away=NS(time_left=timedelta(seconds=7)))],
    ]
    fake = FakeLive(batches)
    s = await GeminiLiveVertex(fake.factory).open(params())
    got = await collect(s)
    assert got == [
        AudioOut(b"AA"),
        ResumptionHandle("H2"),
        Interrupted(),
        TurnComplete(),
        GoAway(7.0),
        Closed("ConnectionError"),
    ]


async def test_gemini_close_yields_closed_and_open_failure():
    fake = FakeLive([[audio(b"A")]])
    s = await GeminiLiveVertex(fake.factory).open(params())
    it = s.events()
    assert await anext(it) == AudioOut(b"A")
    await s.close()
    assert [e async for e in it] == [Closed("closed")]
    bad = FakeLive([], connect_error=RuntimeError(f"boom {SECRET}"))
    with pytest.raises(VoiceProviderError) as ei:
        await GeminiLiveVertex(bad.factory).open(params())
    assert SECRET not in str(ei.value)


async def test_system_prompt_never_logged():
    buf = io.StringIO()
    h = logging.StreamHandler(buf)
    log.addHandler(h)
    old = log.level
    log.setLevel(logging.DEBUG)
    try:
        fake = FakeLive([])
        await GeminiLiveVertex(fake.factory).open(params())
    finally:
        log.removeHandler(h)
        log.setLevel(old)
    assert "voice_open" in buf.getvalue() and SECRET not in buf.getvalue()


# ---- no provider leakage ------------------------------------------------------------------


def test_provider_name_only_in_adapter_and_config():
    root = REPO / "engines" / "core" / "src" / "onolys_core"
    allowed = {"gemini_live_vertex.py", "voice_providers.default.yaml"}
    for f in root.rglob("*"):
        if f.suffix not in (".py", ".yaml") or "__pycache__" in f.parts or f.name in allowed:
            continue
        if f.parent.name == "voice" or "voice" in f.parts:
            text = f.read_text().lower()
            assert "gemini" not in text and "genai" not in text, f
