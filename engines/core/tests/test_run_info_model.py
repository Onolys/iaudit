import json

import pytest
from pydantic import ValidationError

from onolys_core.llm.routes import Route
from onolys_core.run_info import (
    PackFacts,
    RunInfo,
    RunUsage,
    code_version,
    provider_of,
    route_facts,
)
from onolys_core.stt import SttRun

SECRET = "sk-ant-SECRETVALUE"


def _route(**kw):
    return Route(litellm_id="anthropic/claude-sonnet-5-5", api_key_env="ANTHROPIC_API_KEY", **kw)


def test_provider_from_prefix():
    assert provider_of("anthropic/claude-x") == "anthropic"
    assert provider_of("vertex_ai/gemini-2") == "vertex_ai"
    assert provider_of("bare-model") == "unknown"


def test_route_facts_temperature_and_hash(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", SECRET)
    f = route_facts(_route())
    assert f.provider == "anthropic" and f.temperature_effective == 0.0
    assert f.structured_output_mode == "json_object"
    assert route_facts(_route(supports_temperature=False)).temperature_effective is None
    assert f.params_hash == route_facts(_route()).params_hash
    assert f.params_hash != route_facts(_route(max_output_tokens=1)).params_hash
    assert SECRET not in f.model_dump_json()


def test_code_version_from_env(monkeypatch):
    monkeypatch.setenv("GIT_SHA", "abc123")
    assert code_version() == "abc123"
    monkeypatch.delenv("GIT_SHA")
    assert code_version() == "unknown"


def test_run_info_validates_and_has_no_text_or_key(monkeypatch):
    monkeypatch.setenv("GIT_SHA", "abc123")
    monkeypatch.setenv("ANTHROPIC_API_KEY", SECRET)
    stt = SttRun(provider="google", model="chirp_3", language_requested="auto", adapter_version="1")
    ri = RunInfo(
        engine="eaudit",
        code_version=code_version(),
        preset="default",
        routes={"mid": route_facts(_route())},
        stt=stt,
        pack=PackFacts(id="p", version="1", hash="h"),
        prompt_hashes={"atomize": "0123456789abcdef"},
        usage=RunUsage(calls=2, input_tokens=5),
    )
    dumped = json.loads(ri.model_dump_json())
    assert dumped["code_version"] == "abc123" and dumped["n_runs"] == 1
    assert set(dumped["routes"]["mid"]) == {
        "litellm_id",
        "provider",
        "structured_output_mode",
        "temperature_effective",
        "params_hash",
    }
    assert SECRET not in json.dumps(dumped)
    assert RunInfo.model_validate(dumped) == ri
    with pytest.raises(ValidationError):
        RunInfo.model_validate({**dumped, "text": "x"})
