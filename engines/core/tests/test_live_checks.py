"""Offline pass/fail logic of llm.smoke and stt.check, plus `live` wrappers (skipped by default)."""

import os

import pytest

from onolys_core.errors import ConfigError
from onolys_core.llm import FailingClient, LLMResult, Usage, smoke
from onolys_core.llm.errors import LLMBadOutput
from onolys_core.llm.routes import Route
from onolys_core.stt import AudioRef, Word, check
from onolys_core.stt.fixture import FixtureStt, uri_hash
from onolys_core.transcript import Transcript, Turn

pytestmark = pytest.mark.unit

ROUTES = {
    "mid": Route(litellm_id="anthropic/x", api_key_env="K"),
    "tips": Route(litellm_id="anthropic/x", api_key_env="K"),
}


class Client:
    """Fixture client: per-route behaviour for complete_json."""

    def __init__(self, fail=(), wrong=()):
        self.fail, self.wrong, self.seen = set(fail), set(wrong), []

    async def complete_json(self, req, metrics=None):
        self.seen.append(req.tier)
        if req.tier in self.fail:
            raise LLMBadOutput("bad")
        parsed = {"nope": 1} if req.tier in self.wrong else smoke.SmokeReply(ok=True)
        return LLMResult(
            parsed=parsed,
            usage=Usage(input_tokens=12, output_tokens=3),
            latency_ms=42.0,
            model="m-1",
            attempts=1,
        )


async def test_smoke_calls_every_route_and_passes():
    c = Client()
    results = await smoke.run_smoke(c, ROUTES)
    assert c.seen == ["mid", "tips"]
    assert smoke.smoke_passed(results)
    r = results[0]
    assert (r.model, r.latency_ms, r.input_tokens, r.output_tokens) == ("m-1", 42.0, 12, 3)
    out = smoke.format_results(results)
    assert "m-1" in out and "2/2 routes passed" in out and "PASS" in out


async def test_smoke_fails_when_a_route_errors_but_continues():
    c = Client(fail={"mid"})
    results = await smoke.run_smoke(c, ROUTES)
    assert c.seen == ["mid", "tips"]
    assert [r.ok for r in results] == [False, True]
    assert "LLMBadOutput" in results[0].error
    assert not smoke.smoke_passed(results)
    assert "1/2 routes passed" in smoke.format_results(results)


async def test_smoke_fails_on_wrong_schema_result():
    results = await smoke.run_smoke(Client(wrong={"tips"}), ROUTES)
    assert not results[1].ok and not smoke.smoke_passed(results)


async def test_smoke_failing_client_and_empty():
    results = await smoke.run_smoke(FailingClient(RuntimeError("down")), ROUTES)
    assert not smoke.smoke_passed(results)
    assert not smoke.smoke_passed([])


def test_smoke_main_exit_codes(capsys):
    rc = smoke.main(["--preset", "default"], client=Client())
    assert rc == 0
    assert "routes passed" in capsys.readouterr().out
    assert smoke.main([], client=FailingClient(RuntimeError("x"))) == 1


def test_smoke_main_missing_key_is_config_error(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(ConfigError, match="ANTHROPIC_API_KEY"):
        smoke.main(["--preset", "default"])


# ---- stt.check -------------------------------------------------------------------------


def turns(*specs):
    return [
        Turn(id=f"t{i}", speaker=sp, text="x", start_ms=s, end_ms=e)
        for i, (sp, s, e) in enumerate(specs, 1)
    ]


def tr(ts, duration_ms=11 * 60_000):
    return Transcript(turns=ts, duration_ms=duration_ms, language="en-US")


GOOD = [("S1", 0, 1000), ("S2", 1000, 2000), ("S1", 2000, 3000)]


def test_evaluate_passes():
    r = check.evaluate(tr(turns(*GOOD)), 12.5)
    assert r.passed and r.speakers == 2 and r.wall_s == 12.5
    out = check.format_result(r)
    assert "wall time: 12.5s" in out and out.endswith("PASS")


@pytest.mark.parametrize(
    "ts, duration, needle",
    [
        ([("S1", 0, 1000), ("S1", 1000, 2000)], 11 * 60_000, "1 speaker"),
        ([("S1", 0, 1000), ("S2", 500, 900)], 11 * 60_000, "not monotonic"),
        ([("S1", 0, 1000), ("S2", 900, 2000), ("S1", 800, 3000)], 11 * 60_000, "not monotonic"),
        ([("S1", 500, 100), ("S2", 600, 700)], 11 * 60_000, "start_ms > end_ms"),
        (GOOD, 4 * 60_000, "need 5+"),
        ([], 11 * 60_000, "no turns"),
    ],
)
def test_evaluate_fails(ts, duration, needle):
    r = check.evaluate(tr(turns(*ts), duration), 1.0)
    assert not r.passed
    assert any(needle in p for p in r.problems), r.problems
    assert check.format_result(r).endswith("FAIL")


def test_evaluate_missing_offsets():
    ts = [Turn(id="t1", speaker="S1", text="x"), Turn(id="t2", speaker="S2", text="y")]
    r = check.evaluate(tr(ts), 1.0)
    assert not r.passed and any("no start_ms" in p for p in r.problems)


def test_evaluate_default_min_is_5_minutes():
    # owner decision 2026-11-20: real sample is 6.7 min, so the default minimum is 5
    assert check.DEFAULT_MIN_MINUTES == 5
    assert check.evaluate(tr(turns(*GOOD), int(6.7 * 60_000)), 1.0).passed
    r = check.evaluate(tr(turns(*GOOD), 4 * 60_000), 1.0)
    assert not r.passed and any("need 5+" in p for p in r.problems)


def test_evaluate_min_minutes_override():
    assert check.evaluate(tr(turns(*GOOD), 60_000), 1.0, min_minutes=1).passed


def test_build_params_sets_project_and_speakers(monkeypatch):
    monkeypatch.delenv("GOOGLE_CLOUD_PROJECT", raising=False)
    p = check.build_params("default", None, None)
    assert p.provider == "google" and p.options["project"] == "onolys"
    assert (p.speakers_min, p.speakers_max, p.language) == (2, 2, "auto")
    assert p.options["location"] == "us"
    assert check.build_params("default", "en-US", "other").options["project"] == "other"
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "envproj")
    assert check.build_params("default", None, None).options["project"] == "envproj"


def words(n_minutes=11):
    out, t = [], 0
    for i in range(n_minutes * 6):
        out.append(Word(text="w", start_ms=t, end_ms=t + 9000, speaker="a" if i % 2 else "b"))
        t += 10_000
    return out


async def test_run_check_with_fixture_adapter():
    audio = AudioRef(uri="gs://b/s.wav", mime="audio/wav")
    params = check.build_params("default", None, None)
    adapter = FixtureStt({uri_hash(audio.uri): words()}, polls_before_ready=1)
    ticks = iter([100.0, 107.5])
    r = await check.run_check(adapter, audio, params, interval_s=0, clock=lambda: next(ticks))
    assert r.passed and r.wall_s == 7.5


async def test_run_check_one_speaker_fails():
    audio = AudioRef(uri="gs://b/s.wav", mime="audio/wav")
    params = check.build_params("default", None, None)
    one = [w.model_copy(update={"speaker": "a"}) for w in words()]
    r = await check.run_check(FixtureStt({uri_hash(audio.uri): one}), audio, params, interval_s=0)
    assert not r.passed


def test_check_main_exit_codes(capsys):
    uri = "gs://b/s.wav"
    ok = FixtureStt({uri_hash(uri): words()})
    assert check.main(["--audio", uri, "--interval-s", "0.01"], adapter=ok) == 0
    assert "PASS" in capsys.readouterr().out
    bad = FixtureStt({uri_hash(uri): words(2)})
    assert check.main(["--audio", uri, "--interval-s", "0.01"], adapter=bad) == 1


# ---- live wrappers (skipped in PR CI; real runs are Task 13) ----------------------------


@pytest.mark.live
def test_live_llm_smoke():
    assert smoke.main(["--preset", "default"]) == 0


@pytest.mark.live
def test_live_stt_check():
    audio = os.environ.get("STT_CHECK_AUDIO")
    if not audio:
        pytest.skip("set STT_CHECK_AUDIO to a gs:// 2-speaker sample of 10+ min")
    assert check.main(["--audio", audio, "--preset", "default"]) == 0
