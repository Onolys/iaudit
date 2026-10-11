import pytest
from pydantic import ValidationError

from iaudit_backend.config import Settings


def test_defaults():
    s = Settings()
    assert s.max_body_bytes == 2_000_000
    assert s.max_turns == 2000
    assert s.max_sections == 50
    assert s.cors_origins == ["http://localhost:5173"]
    assert s.model_cheap == "anthropic/claude-haiku-4-5-20251001"
    assert s.model_mid == "anthropic/claude-sonnet-5-5"
    assert s.model_strong == "anthropic/claude-opus-5-5"
    assert s.llm_timeout_s == 30
    assert s.audit_deadline_s == 60
    assert s.llm_max_retries == 1
    assert s.llm_max_concurrency == 20
    assert s.llm_mode == "live"
    assert s.pipeline == "stub"
    assert s.log_level == "INFO"


def test_env_overrides(monkeypatch):
    monkeypatch.setenv("IAUDIT_MAX_TURNS", "5")
    monkeypatch.setenv("IAUDIT_CORS_ORIGINS", "http://a.test, http://b.test")
    monkeypatch.setenv("IAUDIT_LLM_MODE", "fixture")
    monkeypatch.setenv("IAUDIT_PIPELINE", "full")
    s = Settings()
    assert s.max_turns == 5
    assert s.cors_origins == ["http://a.test", "http://b.test"]
    assert s.llm_mode == "fixture"
    assert s.pipeline == "full"


def test_frozen():
    with pytest.raises(ValidationError):
        Settings().max_turns = 1


def test_no_secret_fields_and_safe_summary(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-secret-123")
    s = Settings()
    assert not any("key" in f.lower() for f in Settings.model_fields)
    assert "sk-secret-123" not in repr(s.safe_summary())
    assert "sk-secret-123" not in s.model_dump_json()


def test_bad_mode_rejected(monkeypatch):
    monkeypatch.setenv("IAUDIT_LLM_MODE", "bogus")
    with pytest.raises(ValidationError):
        Settings()
