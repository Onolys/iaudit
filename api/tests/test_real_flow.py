"""SP09 Task 5 / R1-R4 / D2 / AC1-AC2: the SP04 end-to-end flow with `ADAPTERS=real`.

No network: the STT provider is `FixtureStt` (via the real `RealStt` registry), the LLM client is
a `StubClient` (tips), and the engine's paudit / reasons-audit seams return canned fixture
results (same approach as `test_run_artifacts.py`). Everything else is real: `build_adapters`,
`RealEvaluation`, `run_evaluation`, report assembly, the worker and its `to_public` error map.
The card is a real-shaped SP02 card with reasons, so the reasons-audit path runs.
"""

import sys
import uuid
from dataclasses import replace
from pathlib import Path

import httpx
import pytest
from audio_helpers import MAGIC, StubTools
from cards import valid_card
from eaudit.models import AuditResponse, Status
from google.api_core import exceptions as gexc
from onolys_core.errors import InputError
from onolys_core.llm import LLMUnavailable, StubClient
from onolys_core.run_info import RunInfo
from onolys_core.stt.fixture import FixtureStt, uri_hash
from onolys_core.transcript import Transcript
from paudit.engine import AllRunsFailed
from test_transcribe import words

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "engines/evaluation/tests"))
from _make_fixtures import inputs  # noqa: E402
from test_tips import good  # noqa: E402

from onolys_api.adapters import build_adapters  # noqa: E402
from onolys_api.adapters.real import RealEvaluation, RealStt  # noqa: E402
from onolys_api.app import create_app  # noqa: E402
from onolys_api.jobs.transcribe import TRANSCRIPT_ID  # noqa: E402
from onolys_api.repo.fake import FakeRepo  # noqa: E402

pytestmark = pytest.mark.integration
FIX = inputs("full")
ROUTES = (
    "cheap: &s {litellm_id: anthropic/x, api_key_env: K}\nmid: *s\nstrong: *s\n"
    "paudit_code: {alias: mid}\npaudit_globals: {alias: mid}\ntips: {alias: mid}\n"
    "presets:\n  default: {routes: {}}\n  fast: {routes: {}}\n"
)


class SpyStt(FixtureStt):
    """Fixture STT for any audio uri; counts submits; optionally fails its first poll."""

    def __init__(self, fail_first_poll: BaseException | None = None) -> None:
        super().__init__({})
        self.fail_first_poll = fail_first_poll
        self.fetches = 0

    async def _submit(self, audio, params):
        self._fixtures[uri_hash(audio.uri)] = words({"A": 60, "B": 60})
        return await super()._submit(audio, params)

    async def _fetch(self, handle):
        self.fetches += 1
        if self.fail_first_poll is not None and self.fetches == 1:
            raise self.fail_first_poll
        return await super()._fetch(handle)


class Engine:
    """Canned paudit / reasons-audit seams; `paudit_failures` are raised one per call first."""

    def __init__(self, monkeypatch, paudit_failures: list[BaseException]) -> None:
        from onolys_evaluation import api

        self.paudit_calls = 0
        self.eaudit_calls = 0
        failures = list(paudit_failures)

        async def fake_paudit(transcript, pack, params, ctx, metrics):
            self.paudit_calls += 1
            if failures:
                raise failures.pop(0)
            return FIX["paudit_result"]

        async def fake_eaudit(request, ctx, metrics):
            self.eaudit_calls += 1
            resp = AuditResponse(request_id="r", status=Status.complete, warnings=[], claims=[])
            return resp, RunInfo(engine="eaudit", code_version="t", preset="default")

        monkeypatch.setattr(api, "_run_paudit", fake_paudit)
        monkeypatch.setattr(api, "_run_eaudit", fake_eaudit)


def fixture_llm(routes: dict) -> StubClient:
    stub = StubClient()
    for tag in ("tips:r0", "tips:r0:retry"):
        stub.register(tag, {"tips": good(3)})
    return stub


class Env:
    def __init__(self, app, client, repo, stt, engine):
        self.app, self.c, self.repo, self.stt, self.engine = app, client, repo, stt, engine
        self.uid = f"u{uuid.uuid4().hex[:10]}"
        self.h = {"Authorization": f"Bearer test:{self.uid}"}

    async def status(self, sid):
        r = await self.c.get(f"/v1/sessions/{sid}", headers=self.h)
        return r.json()

    async def to_awaiting_input(self) -> str:
        r = await self.c.post("/v1/sessions", json={"title": None}, headers=self.h)
        sid = r.json()["session"]["id"]
        up = (
            await self.c.post(
                f"/v1/sessions/{sid}/audio",
                json={"content_type": "audio/wav", "size_bytes": len(MAGIC["wav"])},
                headers=self.h,
            )
        ).json()
        await self.c.put(
            up["upload_url"].removeprefix("http://localhost:8000"),
            content=MAGIC["wav"],
            headers=up["required_headers"],
        )
        await self.c.post(f"/v1/sessions/{sid}/audio/complete", headers=self.h)
        self.app.state.queue.drain()
        return sid

    async def run(self, sid: str, card: dict) -> None:
        await self.c.post(
            f"/v1/sessions/{sid}/speakers/confirm", json={"clinician_speaker": "S1"}, headers=self.h
        )
        r = await self.c.put(
            f"/v1/sessions/{sid}/rating", json={"final": True, "card": card}, headers=self.h
        )
        assert r.status_code in (200, 202), r.text
        # the fixture transcript + its speaker replace the STT one before the run task executes
        self.repo.put_transcript(
            self.uid, sid, TRANSCRIPT_ID, Transcript.model_validate(FIX["transcript"].model_dump())
        )
        self.repo.update_session(self.uid, sid, {"clinician_speaker": "A"})
        self.app.state.queue.drain()


@pytest.fixture
def make_env(settings, blobs, tmp_path, monkeypatch):
    routes = tmp_path / "routes.yaml"
    routes.write_text(ROUTES)
    (tmp_path / "stt_providers.yaml").write_text(
        "providers:\n  base: {provider: p1, model: m1}\ndefault: base\nby_language: {}\n"
    )
    stack: list = []

    async def make(paudit_failures=(), stt_failure=None) -> Env:
        stt = SpyStt(stt_failure)
        engine = Engine(monkeypatch, list(paudit_failures))
        s = replace(settings, routes_file=str(routes), adapters="real")
        adapters = build_adapters(s, stt_registry={"p1": lambda: stt}, llm_factory=fixture_llm)
        repo = FakeRepo(blobs)
        app = create_app(s, repo=repo, blobs=blobs, audio_tools=StubTools(), adapters=adapters)
        client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t")
        stack.append(client)
        return Env(app, client, repo, stt, engine)

    yield make
    # clients are closed by GC with the loop; nothing else to release


def test_build_adapters_real_returns_real_adapters(settings):
    a = build_adapters(replace(settings, adapters="real"))
    assert isinstance(a.stt, RealStt) and isinstance(a.evaluation, RealEvaluation)


async def test_real_flow_reaches_report_ready_with_reasons_audit(make_env):
    env = await make_env()
    sid = await env.to_awaiting_input()
    assert (await env.status(sid))["status"] == "awaiting_input"
    await env.run(sid, valid_card())
    s = await env.status(sid)
    assert (s["status"], s["progress"], s["latest_report_version"]) == ("report_ready", 100, 1)
    assert env.engine.paudit_calls == 1 and env.engine.eaudit_calls == 1
    report = (await env.c.get(f"/v1/sessions/{sid}/reports/1", headers=env.h)).json()["report"]
    assert report["reasons_audit"]["status"] == "ran"
    assert len(report["tips"]) == 3  # from the fixture LLM client


async def test_stt_start_called_once_across_forced_retry(make_env):
    env = await make_env(stt_failure=gexc.ServiceUnavailable("provider blip"))
    sid = await env.to_awaiting_input()
    # the first poll failed transiently, the queue retried it (attempt 2) and it succeeded
    assert (await env.status(sid))["status"] == "awaiting_input"
    assert env.stt.submits == 1 and env.stt.fetches >= 2


async def test_transient_llm_failure_succeeds_on_attempt_2(make_env):
    env = await make_env(paudit_failures=[LLMUnavailable("overloaded")])
    sid = await env.to_awaiting_input()
    await env.run(sid, valid_card())
    s = await env.status(sid)
    assert s["status"] == "report_ready"
    assert env.engine.paudit_calls == 2


@pytest.mark.parametrize(
    "failure, code",
    [
        (AllRunsFailed("all runs failed"), "internal_error"),
        (InputError("bad preset"), "invalid_parameters"),
    ],
)
async def test_permanent_failure_ends_failed_with_mapped_code(make_env, failure, code):
    env = await make_env(paudit_failures=[failure, failure])
    sid = await env.to_awaiting_input()
    await env.run(sid, valid_card())
    s = await env.status(sid)
    assert s["status"] == "failed" and s["error"]["code"] == code
    assert env.engine.paudit_calls == 1  # not retried


async def test_transient_failure_twice_ends_failed_upstream_unavailable(make_env):
    env = await make_env(paudit_failures=[LLMUnavailable("x"), LLMUnavailable("x")])
    sid = await env.to_awaiting_input()
    await env.run(sid, valid_card())
    s = await env.status(sid)
    assert s["status"] == "failed" and s["error"]["code"] == "upstream_unavailable"
    assert env.engine.paudit_calls == 2
