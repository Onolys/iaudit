import pytest

from onolys_core.errors import InputError
from onolys_core.stt import AudioRef, SttParams, Word
from onolys_core.stt.base import transcribe, words_to_turns
from onolys_core.stt.fixture import FixtureStt, uri_hash
from onolys_core.stt.select import locate_config_file, select_stt

pytestmark = pytest.mark.unit

W = Word
WORDS = [
    W(text="Hello", start_ms=0, end_ms=400, speaker="spk_9"),
    W(text="there", start_ms=450, end_ms=900, speaker="spk_9"),
    W(text="Hi", start_ms=1000, end_ms=1200, speaker="spk_2"),
    W(text="again", start_ms=1250, end_ms=1600, speaker="spk_2"),
    W(text="later", start_ms=9000, end_ms=9400, speaker="spk_2"),
    W(text="back", start_ms=9500, end_ms=9800, speaker="spk_9"),
]


def test_turn_split_speaker_gap_and_normalisation():
    turns = words_to_turns(WORDS, max_gap_ms=2000)
    assert [(t.speaker, t.text) for t in turns] == [
        ("S1", "Hello there"),
        ("S2", "Hi again"),
        ("S2", "later"),
        ("S1", "back"),
    ]
    assert turns[0].start_ms == 0 and turns[0].end_ms == 900
    assert [t.id for t in turns] == ["t1", "t2", "t3", "t4"]


def test_no_gap_split_when_gap_within_limit():
    turns = words_to_turns(WORDS[2:5], max_gap_ms=10_000)
    assert len(turns) == 1


def test_none_speaker_and_empty():
    assert words_to_turns([]) == []
    t = words_to_turns([W(text="x", start_ms=0, end_ms=1)])
    assert t[0].speaker is None


async def test_fixture_two_speakers_and_ms_times():
    audio = AudioRef(uri="gs://b/a.flac", mime="audio/flac")
    stt = FixtureStt({uri_hash(audio.uri): WORDS})
    tr = await transcribe(stt, audio, SttParams(provider="fixture", model="f"))
    assert {t.speaker for t in tr.turns} == {"S1", "S2"}
    assert all(isinstance(t.start_ms, int) and isinstance(t.end_ms, int) for t in tr.turns)
    assert tr.duration_ms == 9800 and tr.stt_run.provider == "fixture"


async def test_handle_resume_without_second_submit():
    audio = AudioRef(uri="gs://b/a.flac", mime="audio/flac")
    stt = FixtureStt({uri_hash(audio.uri): WORDS}, polls_before_ready=2)
    handle = await stt.start(audio, SttParams(provider="fixture", model="f"))
    assert await stt.poll(handle) is None
    # "retry": resume from stored handle only
    assert await stt.poll(handle) is None
    tr = await stt.poll(handle)
    assert tr is not None and stt.submits == 1


async def test_unknown_fixture_raises():
    stt = FixtureStt({})
    with pytest.raises(InputError):
        await stt.start(AudioRef(uri="x", mime="audio/flac"), SttParams(provider="f", model="f"))


async def test_transcribe_max_polls():
    audio = AudioRef(uri="u", mime="audio/flac")
    stt = FixtureStt({uri_hash("u"): WORDS}, polls_before_ready=5)
    with pytest.raises(TimeoutError):
        await transcribe(stt, audio, SttParams(provider="f", model="f"), interval_s=0, max_polls=2)


CFG = {
    "providers": {
        "a": {"provider": "pa", "model": "ma"},
        "b": {"provider": "pb", "model": "mb", "speakers_max": 4, "options": {"k": 1}},
        "c": {"provider": "pc", "model": "mc", "language": "en-US"},
    },
    "default": "a",
    "by_language": {"ja-JP": "b"},
}


def test_select_precedence():
    assert select_stt("c", "ja-JP", config=CFG).provider == "pc"  # preset wins
    assert select_stt(None, "ja-JP", config=CFG).provider == "pb"  # by_language
    assert select_stt(None, "en-US", config=CFG).provider == "pa"  # default
    assert select_stt(None, None, config=CFG).language == "auto"


def test_session_language_wins_and_fields():
    p = select_stt("c", "fr-FR", config=CFG)
    assert p.language == "fr-FR"
    b = select_stt("b", "ja-JP", config=CFG)
    assert b.speakers_max == 4 and b.options == {"k": 1} and b.speakers_min == 2


def test_select_unknown_key():
    with pytest.raises(InputError):
        select_stt("zzz", None, config=CFG)


def test_packaged_default_and_routes_file_dir(tmp_path, monkeypatch):
    monkeypatch.delenv("ROUTES_FILE", raising=False)
    packaged = locate_config_file()
    assert packaged.name == "stt_providers.default.yaml"
    assert select_stt(None, "en-US").provider == "google"
    (tmp_path / "routes.yaml").write_text("{}")
    (tmp_path / "stt_providers.yaml").write_text(
        "providers: {x: {provider: px, model: mx}}\ndefault: x\n"
    )
    monkeypatch.setenv("ROUTES_FILE", str(tmp_path / "routes.yaml"))
    assert locate_config_file() == tmp_path / "stt_providers.yaml"
    assert select_stt(None, None).provider == "px"
