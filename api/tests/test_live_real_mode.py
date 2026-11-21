"""SP09 Task 6 / R5 / AC: local real mode, no GCP. Real LLM, fixture STT.

`ADAPTERS=real`, `SERVICE_MODE=combined`, a local `stt_providers.yaml` whose default is
`provider: fixture`, the shipped Claude Sonnet routes. Real paudit, real reasons audit and real
tips run on the synthetic evaluation fixture transcript; only STT is the fixture provider. The
repo and blob store are the in-memory fakes. Needs ANTHROPIC_API_KEY.

Manual / nightly only (excluded by `-m "not live"`, the api pytest default):

    set -a; . ~/.config/onolys/keys.env; set +a
    uv run --package onolys-api pytest api/tests/test_live_real_mode.py -m live -s
"""

import json
import os
import shutil
import sys
import time
import uuid
from dataclasses import replace
from importlib import resources
from pathlib import Path

import httpx
import pytest
from audio_helpers import MAGIC, StubTools
from jsonschema import Draft202012Validator
from onolys_core.stt.fixture import FixtureStt, uri_hash
from onolys_core.transcript import Transcript
from test_transcribe import words

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "engines/evaluation/tests"))
from _make_fixtures import FULL_RATING, inputs  # noqa: E402

from onolys_api.adapters import build_adapters  # noqa: E402
from onolys_api.app import create_app  # noqa: E402
from onolys_api.jobs.transcribe import TRANSCRIPT_ID  # noqa: E402
from onolys_api.repo.fake import FakeRepo  # noqa: E402

pytestmark = [pytest.mark.live, pytest.mark.integration]
ROOT = Path(__file__).resolve().parents[2]
FIX = inputs("full")
REPORT = Draft202012Validator(
    json.loads((ROOT / "engines/evaluation/schemas/report.schema.json").read_text())
)


CARD = {**FULL_RATING, "change_goal": "Walk more", "coded_span": {"from_s": 0, "to_s": 600}}


class AnyUriFixtureStt(FixtureStt):
    """The `fixture` provider for any audio uri (the api stores a different uri per session)."""

    def __init__(self) -> None:
        super().__init__({})

    async def _submit(self, audio, params):
        self._fixtures[uri_hash(audio.uri)] = words({"A": 60, "B": 60})
        return await super()._submit(audio, params)


def _usages(node):
    """Every `usage` object in the report (`run_info.usage` of each engine)."""
    if isinstance(node, dict):
        if isinstance(node.get("usage"), dict) and "calls" in node["usage"]:
            yield node["usage"]
        for v in node.values():
            yield from _usages(v)
    elif isinstance(node, list):
        for v in node:
            yield from _usages(v)


async def test_real_mode_fixture_stt_real_llm_reaches_report_ready(settings, blobs, tmp_path):
    if not os.environ.get("ANTHROPIC_API_KEY"):
        pytest.skip("set ANTHROPIC_API_KEY (live LLM)")
    cfg = tmp_path / "cfg"
    cfg.mkdir()
    default_routes = resources.files("onolys_core.llm").joinpath("routes.default.yaml")
    shutil.copy(str(default_routes), cfg / "routes.yaml")
    (cfg / "stt_providers.yaml").write_text(
        "providers:\n  fixture: {provider: fixture, model: fixture}\ndefault: fixture\n"
        "by_language: {}\n"
    )
    s = replace(
        settings, adapters="real", service_mode="combined", routes_file=str(cfg / "routes.yaml")
    )
    stt = AnyUriFixtureStt()
    adapters = build_adapters(s, stt_registry={"fixture": lambda: stt})
    repo = FakeRepo(blobs)
    app = create_app(s, repo=repo, blobs=blobs, audio_tools=StubTools(), adapters=adapters)
    uid = f"u{uuid.uuid4().hex[:10]}"
    h = {"Authorization": f"Bearer test:{uid}"}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        sid = (await c.post("/v1/sessions", json={"title": None}, headers=h)).json()["session"][
            "id"
        ]
        up = (
            await c.post(
                f"/v1/sessions/{sid}/audio",
                json={"content_type": "audio/wav", "size_bytes": len(MAGIC["wav"])},
                headers=h,
            )
        ).json()
        await c.put(
            up["upload_url"].removeprefix("http://localhost:8000"),
            content=MAGIC["wav"],
            headers=up["required_headers"],
        )
        await c.post(f"/v1/sessions/{sid}/audio/complete", headers=h)
        app.state.queue.drain()
        got = (await c.get(f"/v1/sessions/{sid}", headers=h)).json()
        assert got["status"] == "awaiting_input"
        # provider comes from the local stt_providers.yaml default
        assert repo.get_session(uid, sid).stt.provider == "fixture"

        await c.post(
            f"/v1/sessions/{sid}/speakers/confirm", json={"clinician_speaker": "S1"}, headers=h
        )
        r = await c.put(f"/v1/sessions/{sid}/rating", json={"final": True, "card": CARD}, headers=h)
        assert r.status_code in (200, 202), r.text
        # the synthetic evaluation fixture transcript (with its speaker) replaces the STT one
        repo.put_transcript(
            uid, sid, TRANSCRIPT_ID, Transcript.model_validate(FIX["transcript"].model_dump())
        )
        repo.update_session(uid, sid, {"clinician_speaker": "A"})
        t0 = time.monotonic()
        app.state.queue.drain()
        duration = time.monotonic() - t0
        got = (await c.get(f"/v1/sessions/{sid}", headers=h)).json()
        assert (got["status"], got["progress"]) == ("report_ready", 100), got
        report = (await c.get(f"/v1/sessions/{sid}/reports/1", headers=h)).json()["report"]
    REPORT.validate(report)
    calls = [u["calls"] for u in _usages(report)]
    print(f"LIVE_OK duration_s={duration:.1f} llm_calls={sum(calls)} usages={len(calls)}")
    assert sum(calls) > 0  # the LLM really ran
    assert stt.submits == 1
