import logging

import pytest

from onolys_core.safe_log import ALLOWED_FIELDS, MAX_VALUE_CHARS, log_event, register_fields
from onolys_core.stt import AudioRef, SttParams, Word
from onolys_core.stt.base import transcribe
from onolys_core.stt.fixture import FixtureStt, uri_hash

pytestmark = pytest.mark.unit

SENTINEL = "ZZ-SENTINEL-PHI-ZZ"
URI = "gs://secret-bucket/patient-0042.flac"


def _log(caplog, **fields):
    with caplog.at_level(logging.INFO, logger="iaudit"):
        caplog.clear()
        log_event("ev", **fields)
    return caplog.text


@pytest.mark.parametrize(
    "name", ["text", "body", "transcript", "excerpt", "message", "turn_text", "error_message"]
)
def test_blocked_parts_dropped_even_if_registered(caplog, name):
    register_fields(frozenset({name}))
    try:
        assert SENTINEL not in _log(caplog, **{name: SENTINEL})
    finally:
        ALLOWED_FIELDS.discard(name)


def test_unknown_field_dropped_and_audio_uri_not_loggable(caplog):
    out = _log(caplog, surprise=SENTINEL, audio_uri=URI, uri=URI, rating=5)
    assert SENTINEL not in out and URI not in out and "rating" not in out


def test_new_generic_fields_allowed(caplog):
    out = _log(
        caplog,
        audio_ms=1200,
        stt_provider="fixture",
        stt_model="m",
        language="en",
        speakers=2,
        job_id="j1",
        step="submit",
    )
    for s in (
        "audio_ms=1200",
        'stt_provider="fixture"',
        'stt_model="m"',
        'language="en"',
        "speakers=2",
        'job_id="j1"',
        'step="submit"',
    ):
        assert s in out


def test_register_fields_adds_engine_field(caplog):
    register_fields(frozenset({"zz_engine_field"}))
    try:
        assert "zz_engine_field=3" in _log(caplog, zz_engine_field=3)
    finally:
        ALLOWED_FIELDS.discard("zz_engine_field")


def test_value_cap_and_escaping(caplog):
    out = _log(caplog, request_id="a" * 500 + "\nforged=1")
    assert "a" * MAX_VALUE_CHARS in out and "a" * (MAX_VALUE_CHARS + 1) not in out
    assert "\nforged" not in out


async def test_full_fixture_stt_call_logs_no_text_or_uri(caplog):
    words = [
        Word(text=SENTINEL, start_ms=0, end_ms=400, speaker="a"),
        Word(text="other", start_ms=500, end_ms=900, speaker="b"),
    ]
    audio = AudioRef(uri=URI, mime="audio/flac", duration_ms=900)
    stt = FixtureStt({uri_hash(URI): words}, polls_before_ready=1)
    with caplog.at_level(logging.DEBUG, logger="iaudit"):
        await transcribe(
            stt, audio, SttParams(provider="fixture", model="fx", language="en"), interval_s=0
        )
    assert "stt_provider" in caplog.text and 'stt_model="fx"' in caplog.text
    assert "audio_ms=900" in caplog.text and "speakers=2" in caplog.text
    assert "job_id=" in caplog.text
    for banned in (SENTINEL, "other", URI, "secret-bucket", "patient-0042"):
        assert banned not in caplog.text
