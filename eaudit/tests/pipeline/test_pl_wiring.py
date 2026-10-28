import logging

from fastapi.testclient import TestClient

from eaudit.app import create_app
from eaudit.config import Settings
from eaudit.pipeline import StubPipeline
from eaudit.pipeline.full import FullPipeline


def test_default_serves_full_and_env_pins_stub(monkeypatch):
    with TestClient(create_app(Settings(llm_mode="stub"))) as c:
        assert isinstance(c.app.state.pipeline, FullPipeline)
    monkeypatch.setenv("IAUDIT_PIPELINE", "stub")
    with TestClient(create_app(Settings(llm_mode="stub"))) as c:
        assert isinstance(c.app.state.pipeline, StubPipeline)


def test_long_deadline_warns_at_startup(caplog):
    with caplog.at_level(logging.WARNING, logger="iaudit"):
        with TestClient(create_app(Settings(llm_mode="stub", audit_deadline_s=120))):
            pass
        assert "audit_deadline_s=120" in caplog.text
        caplog.clear()
        with TestClient(create_app(Settings(llm_mode="stub"))):
            pass
        assert "audit_deadline_s" not in caplog.text


def test_live_mode_without_key_warns_by_presence_only(monkeypatch, caplog):
    for k in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "LITELLM_API_KEY"):
        monkeypatch.delenv(k, raising=False)
    with caplog.at_level(logging.WARNING, logger="iaudit"):
        with TestClient(create_app(Settings(llm_mode="live"))):
            pass
    assert "no provider API key" in caplog.text


def test_unavailable_provider_is_503_through_the_real_pipeline(example_request):
    from eaudit.llm import FailingClient, LLMUnavailable

    app = create_app(Settings(llm_mode="stub"), llm=FailingClient(LLMUnavailable("down")))
    with TestClient(app) as c:
        r = c.post("/v1/audit", json=example_request)
    assert r.status_code == 503 and r.json()["error"]["code"] == "unavailable"
