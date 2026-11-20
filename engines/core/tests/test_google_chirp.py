import json
import subprocess
import sys
from datetime import timedelta
from types import SimpleNamespace as NS

import pytest

from onolys_core.errors import InputError
from onolys_core.stt import AudioRef, SttParams
from onolys_core.stt import Word
from onolys_core.stt.base import transcribe, words_to_turns
from onolys_core.stt.google_chirp import (
    GoogleChirp3,
    SttProviderError,
    build_batch_request,
    extract_words,
    location_endpoint,
    resolve_location,
)
from onolys_core.stt.select import select_stt

pytestmark = pytest.mark.unit

AUDIO = AudioRef(uri="gs://b/o/canonical.flac", mime="audio/flac")


def params(**kw) -> SttParams:
    base = dict(
        provider="google",
        model="chirp_3",
        options={
            "recognition": "standard",
            "location": "us",
            "endpoint": "us-speech.googleapis.com",
        },
    )
    return SttParams(**{**base, **kw})


def test_diarization_bounds_from_params():
    req = build_batch_request(AUDIO, params(speakers_min=2, speakers_max=4), "proj")
    d = req["config"]["features"]["diarization_config"]
    assert d == {"min_speaker_count": 2, "max_speaker_count": 4}
    assert req["config"]["features"]["enable_word_time_offsets"] is True
    assert req["recognizer"] == "projects/proj/locations/us/recognizers/_"
    assert req["config"]["model"] == "chirp_3"
    assert req["files"] == [{"uri": AUDIO.uri}]
    assert "inline_response_config" in req["recognition_output_config"]


def test_diarization_off_and_bad_bounds():
    req = build_batch_request(AUDIO, params(diarization=False), "p")
    assert "diarization_config" not in req["config"]["features"]
    with pytest.raises(InputError):
        build_batch_request(AUDIO, params(speakers_min=3, speakers_max=2), "p")


def test_language_auto_and_explicit():
    assert build_batch_request(AUDIO, params(), "p")["config"]["language_codes"] == ["auto"]
    req = build_batch_request(AUDIO, params(language="en-US"), "p")
    assert req["config"]["language_codes"] == ["en-US"]


def test_location_to_endpoint():
    assert location_endpoint("us") == "us-speech.googleapis.com"
    assert location_endpoint("eu") == "eu-speech.googleapis.com"
    assert location_endpoint("global") == "speech.googleapis.com"
    assert resolve_location(params(options={"location": "eu"})) == (
        "eu",
        "eu-speech.googleapis.com",
    )
    assert resolve_location(params(options={})) == ("us", "us-speech.googleapis.com")


def test_non_gcs_uri_rejected():
    with pytest.raises(InputError):
        build_batch_request(AudioRef(uri="/tmp/a.flac", mime="audio/flac"), params(), "p")


def test_default_entry_wires_adapter_params():
    p = select_stt(None, "en-US")
    assert (p.provider, p.model, p.options["location"]) == ("google", "chirp_3", "us")
    assert p.options["endpoint"] == "us-speech.googleapis.com"


def _word(w, s, e, spk):
    return NS(
        word=w,
        start_offset=timedelta(milliseconds=s),
        end_offset=timedelta(milliseconds=e),
        speaker_label=spk,
    )


def _response(words_a, lang="en-us", error=None):
    res = NS(alternatives=[NS(words=words_a)], language_code=lang)
    fr = NS(error=error, transcript=NS(results=[res]))
    return NS(results={"gs://b/o/canonical.flac": fr})


class FakeBackend:
    def __init__(self, response, ready_after=0):
        self.response, self.ready_after = response, ready_after
        self.submits, self.gets, self.last = 0, 0, None

    def project(self):
        return "proj"

    def submit(self, request, endpoint):
        self.submits += 1
        self.last = (request, endpoint)
        return "projects/proj/locations/us/operations/42"

    def get(self, name, endpoint):
        assert name.endswith("/operations/42") and endpoint == "us-speech.googleapis.com"
        self.gets += 1
        return None if self.gets <= self.ready_after else self.response


async def test_start_poll_words_speakers_ms():
    resp = _response([_word("Hello", 0, 400, "1"), _word("Hi", 1000, 1200, "2")])
    be = FakeBackend(resp, ready_after=1)
    ad = GoogleChirp3(be)
    handle = await ad.start(AUDIO, params())
    json.loads(handle)  # JSON-serialisable handle
    assert be.last[1] == "us-speech.googleapis.com"
    assert be.last[0]["recognizer"].startswith("projects/proj/locations/us/")
    assert await ad.poll(handle) is None
    t = await ad.poll(handle)
    assert be.submits == 1
    assert [(x.speaker, x.text, x.start_ms, x.end_ms) for x in t.turns] == [
        ("S1", "Hello", 0, 400),
        ("S2", "Hi", 1000, 1200),
    ]
    assert t.language == "en-us" and t.stt_run.language_requested == "auto"
    assert t.stt_run.provider == "google" and t.stt_run.location == "us"


async def test_transcribe_helper_and_options_project():
    be = FakeBackend(_response([_word("a", 5, 9, None)]))
    t = await transcribe(
        GoogleChirp3(be),
        AUDIO,
        params(options={"location": "us", "project": "x", "endpoint": "us-speech.googleapis.com"}),
        interval_s=0,
    )
    assert t.turns[0].speaker is None and be.last[0]["recognizer"].startswith("projects/x/")


async def test_file_error_raises_and_bad_handle():
    err = NS(code=3, message="bad audio")
    ad = GoogleChirp3(FakeBackend(_response([], error=err)))
    h = await ad.start(AUDIO, params())
    with pytest.raises(SttProviderError):
        await ad.poll(h)
    with pytest.raises(InputError):
        await ad.poll("not-json")


def test_core_import_does_not_load_google():
    code = (
        "import sys, onolys_core.stt, onolys_core.stt.google_chirp, onolys_core.stt.select;"
        "sys.exit(1 if any(m == 'google' or m.startswith('google.') for m in sys.modules) else 0)"
    )
    assert subprocess.run([sys.executable, "-c", code]).returncode == 0


def test_extract_words_clamps_zero_end_mid_and_last():
    resp = _response(
        [
            _word("a", 100, 200, "1"),
            _word("b", 300, 0, "1"),  # zero end mid-list -> next word's start
            _word("c", 500, 600, "1"),
            _word("d", 700, 0, "1"),  # zero end at the end -> own start
        ]
    )
    words, _ = extract_words(resp)
    assert [(w.text, w.start_ms, w.end_ms) for w in words] == [
        ("a", 100, 200),
        ("b", 300, 500),
        ("c", 500, 600),
        ("d", 700, 700),
    ]


def test_extract_words_end_before_start_and_next_before_start():
    resp = _response([_word("a", 300, 100, None), _word("b", 200, 250, None)])
    words, _ = extract_words(resp)  # never reordered; next start < start -> own start
    assert [(w.text, w.start_ms, w.end_ms) for w in words] == [("a", 300, 300), ("b", 200, 250)]


def test_words_to_turns_end_is_max_word_end_and_not_before_start():
    words = [
        Word(text="a", start_ms=100, end_ms=500, speaker="1"),
        Word(text="b", start_ms=200, end_ms=0, speaker="1"),
        Word(text="c", start_ms=900, end_ms=0, speaker="2"),
    ]
    turns = words_to_turns(words)
    assert [(t.start_ms, t.end_ms) for t in turns] == [(100, 500), (900, 900)]


async def test_zero_end_word_end_to_end_turns_valid():
    resp = _response([_word("a", 100, 200, "1"), _word("b", 300, 0, "1")])
    t = await transcribe(GoogleChirp3(FakeBackend(resp)), AUDIO, params(), interval_s=0)
    assert all(x.start_ms <= x.end_ms for x in t.turns)
