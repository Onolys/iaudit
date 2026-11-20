"""SP09 R1/D5/AC1: the real `Stt` adapter is a registry over the SP01 core adapters, chosen by
the session's stored `stt.provider`. Unit tests use `FixtureStt`; no live STT."""

import json

import pytest
from onolys_core.errors import ConfigError
from onolys_core.stt import AudioRef, SttParams
from onolys_core.stt.fixture import FixtureStt, uri_hash
from onolys_core.stt.google_chirp import GoogleChirp3
from test_transcribe import SID, UID, Env, words

from onolys_api.adapters.error_map import INTERNAL, to_public
from onolys_api.adapters.real import DEFAULT_REGISTRY, RealStt
from onolys_api.audio import canonical_audio_ref, canonical_key
from onolys_api.repo.models import RecordingDoc

pytestmark = pytest.mark.unit
URI = "gs://b/u1/s1/audio/canonical.flac"
PARAMS = SttParams(provider="fixture", model="fixture", language="en")


def audio(uri: str = URI) -> AudioRef:
    return AudioRef(uri=uri, mime="audio/flac", duration_ms=1000)


def fixture_for(uri: str = URI, **kw) -> FixtureStt:
    return FixtureStt({uri_hash(uri): words({"A": 60, "B": 60})}, **kw)


async def test_registry_lookup_picks_adapter_by_stored_provider():
    other = fixture_for()
    stt = RealStt({"fixture": lambda: fixture_for(), "other": lambda: other})
    handle = await stt.start(audio(), PARAMS.model_copy(update={"provider": "other"}))
    assert other.submits == 1
    assert (await stt.poll(handle)) is not None


def test_default_registry_has_the_two_core_providers():
    assert {"google_chirp", "fixture"} <= set(DEFAULT_REGISTRY)
    assert isinstance(DEFAULT_REGISTRY["google_chirp"](), GoogleChirp3)
    # the packaged stt_providers.yaml stores provider `google` for the Chirp 3 entry
    assert isinstance(DEFAULT_REGISTRY["google"](), GoogleChirp3)


async def test_unknown_provider_is_a_config_error_mapped_to_internal_error():
    stt = RealStt({"fixture": lambda: fixture_for()})
    with pytest.raises(ConfigError) as ei:
        await stt.start(audio(), PARAMS.model_copy(update={"provider": "nope"}))
    assert to_public(ei.value, 1, "stt") == (INTERNAL, False)
    with pytest.raises(ConfigError):
        await stt.poll(json.dumps({"provider": "nope", "handle": "x"}))
    with pytest.raises(ConfigError):
        await stt.poll("not-json")


async def test_audio_ref_and_params_reach_the_core_adapter_unchanged():
    seen: list[tuple[AudioRef, SttParams]] = []

    class Spy(FixtureStt):
        async def _submit(self, a, p):
            seen.append((a, p))
            return await super()._submit(a, p)

    stt = RealStt({"fixture": lambda: Spy({uri_hash(URI): words({"A": 5})})})
    ref = AudioRef(uri=URI, mime="audio/flac", duration_ms=123_000)
    await stt.start(ref, PARAMS)
    assert seen == [(ref, PARAMS)]


def test_canonical_audio_ref_points_at_canonical_flac(blobs):
    rec = RecordingDoc(gcs_uri="gs://b/x", duration_ms=600_000)
    ref = canonical_audio_ref(blobs, UID, SID, rec)
    assert ref.uri == blobs.uri(canonical_key(UID, SID))
    assert ref.uri.endswith("/audio/canonical.flac")
    assert ref.mime == "audio/flac" and ref.duration_ms == 600_000


async def test_transcript_passes_through_with_stt_run_unchanged():
    direct = fixture_for()
    h = await direct.start(audio(), PARAMS)
    want = await direct.poll(h)
    stt = RealStt({"fixture": lambda: fixture_for()})
    got = await stt.poll(await stt.start(audio(), PARAMS))
    assert got == want and got.stt_run.provider == "fixture"


async def test_poll_returns_none_while_running_and_never_resubmits():
    core = fixture_for(polls_before_ready=2)
    stt = RealStt({"fixture": lambda: core})
    h = await stt.start(audio(), PARAMS)
    assert await stt.poll(h) is None and await stt.poll(h) is None
    assert await stt.poll(h) is not None
    assert core.submits == 1


async def test_handle_is_a_json_string_routing_poll_to_its_provider():
    a, b = fixture_for(), fixture_for()
    stt = RealStt({"a": lambda: a, "b": lambda: b})
    h = await stt.start(audio(), PARAMS.model_copy(update={"provider": "b"}))
    assert isinstance(h, str) and json.loads(h)["provider"] == "b"
    await stt.poll(h)
    assert (a.submits, b.submits) == (0, 1)


async def test_a_new_provider_needs_only_a_registry_line():
    newcore = fixture_for()
    registry = {**DEFAULT_REGISTRY, "brand_new": lambda: newcore}  # the one line
    stt = RealStt(registry)
    h = await stt.start(audio(), PARAMS.model_copy(update={"provider": "brand_new"}))
    assert newcore.submits == 1 and (await stt.poll(h)) is not None


def test_start_called_once_across_retry_and_redelivery(blobs):
    uri = blobs.uri(canonical_key(UID, SID))
    core = FixtureStt({uri_hash(uri): words({"A": 60, "B": 60})})
    env = Env(blobs, RealStt({"fixture": lambda: core}))
    env.repo.update_session(UID, SID, {"stt.provider": "fixture"})
    env.start()
    env.start()  # redelivery
    env.start(retry=1)  # retry
    assert core.submits == 1
    env.run_polls()
    assert env.session.state == "awaiting_input" and core.submits == 1
