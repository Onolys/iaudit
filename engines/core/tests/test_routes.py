import pytest

from onolys_core.errors import ConfigError, InputError
from onolys_core.llm.routes import (
    allowed_presets,
    check_api_keys,
    load_registry,
    resolve_preset,
)

pytestmark = pytest.mark.unit

SONNET = "anthropic/claude-sonnet-5-5"

GEMINI_FILE = """
mid:
  litellm_id: vertex_ai/gemini-2.5-pro
  structured_output_mode: json_schema
  caching_mode: none
  extra_params: {}
cheap: {alias: mid}
strong: {alias: mid}
tips: {alias: cheap}
presets:
  default: {routes: {}}
  fast:
    stt: google_chirp3
    routes:
      mid: {litellm_id: vertex_ai/gemini-2.5-flash}
      tips: {alias: strong}
"""


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for v in (
        "ROUTES_FILE",
        "DEFAULT_PRESET",
        "IAUDIT_MODEL_CHEAP",
        "IAUDIT_MODEL_MID",
        "IAUDIT_MODEL_STRONG",
        "IAUDIT_LLM_RESPONSE_FORMAT",
    ):
        monkeypatch.delenv(v, raising=False)


def test_packaged_default_routes_and_alias():
    routes, stt = resolve_preset()
    assert stt is None
    for name in ("cheap", "mid", "strong", "paudit_code", "paudit_globals", "tips"):
        r = routes[name]
        assert r.litellm_id == SONNET
        assert r.structured_output_mode == "json_object"
        assert r.caching_mode == "anthropic_ephemeral"
        assert r.supports_temperature is False
        assert r.api_key_env == "ANTHROPIC_API_KEY"
        assert "thinking" not in r.extra_params
    assert routes["tips"] == routes["mid"]


def test_routes_file_redirect_and_gemini_route(tmp_path, monkeypatch):
    f = tmp_path / "routes.yaml"
    f.write_text(GEMINI_FILE)
    monkeypatch.setenv("ROUTES_FILE", str(f))
    routes, _ = resolve_preset()
    mid = routes["mid"]
    assert mid.litellm_id == "vertex_ai/gemini-2.5-pro"
    assert mid.structured_output_mode == "json_schema"
    assert mid.caching_mode == "none"
    assert mid.extra_params == {} and mid.api_key_env is None
    assert routes["tips"].litellm_id == mid.litellm_id  # alias chain


def test_routes_file_missing(tmp_path, monkeypatch):
    monkeypatch.setenv("ROUTES_FILE", str(tmp_path / "nope.yaml"))
    with pytest.raises(ConfigError, match="ROUTES_FILE"):
        load_registry()


def test_preset_selection_and_default_preset_env(tmp_path, monkeypatch):
    f = tmp_path / "routes.yaml"
    f.write_text(GEMINI_FILE)
    monkeypatch.setenv("ROUTES_FILE", str(f))
    routes, stt = resolve_preset("fast")
    assert stt == "google_chirp3"
    assert routes["mid"].litellm_id == "vertex_ai/gemini-2.5-flash"
    assert routes["mid"].structured_output_mode == "json_schema"  # merged, not replaced
    assert routes["tips"] == routes["strong"] == routes["mid"]  # tips re-pointed to strong -> mid
    assert resolve_preset("default")[0]["mid"].litellm_id == "vertex_ai/gemini-2.5-pro"
    monkeypatch.setenv("DEFAULT_PRESET", "fast")
    assert resolve_preset()[1] == "google_chirp3"
    assert allowed_presets() == ["default", "fast"]


def test_unknown_preset_raises_input_error(monkeypatch):
    with pytest.raises(InputError):
        resolve_preset("nope")
    monkeypatch.setenv("DEFAULT_PRESET", "nope")
    with pytest.raises(InputError):
        resolve_preset()


def test_env_overrides_back_compat(monkeypatch):
    monkeypatch.setenv("IAUDIT_MODEL_MID", "anthropic/other")
    monkeypatch.setenv("IAUDIT_MODEL_CHEAP", "anthropic/small")
    monkeypatch.setenv("IAUDIT_LLM_RESPONSE_FORMAT", "json_schema")
    routes, _ = resolve_preset()
    assert routes["mid"].litellm_id == "anthropic/other"
    assert routes["tips"].litellm_id == "anthropic/other"  # alias follows mid
    assert routes["cheap"].litellm_id == "anthropic/small"
    assert routes["strong"].litellm_id == SONNET
    assert all(r.structured_output_mode == "json_schema" for r in routes.values())


def test_check_api_keys_names_variable(monkeypatch):
    routes, _ = resolve_preset()
    with pytest.raises(ConfigError, match="ANTHROPIC_API_KEY"):
        check_api_keys(routes, env={})
    check_api_keys(routes, env={"ANTHROPIC_API_KEY": "x"})
    f_routes = {"g": routes["mid"].__class__(litellm_id="vertex_ai/g")}
    check_api_keys(f_routes, env={})  # no api_key_env: nothing to check


@pytest.mark.parametrize(
    "body",
    [
        "mid: {litellm_id: a, structured_output_mode: tool}",
        "mid: {litellm_id: a, caching_mode: weird}",
        "mid: {alias: nope}",
        "mid: {alias: tips}\ntips: {alias: mid}",
        "mid: {litellm_id: a, bogus: 1}",
        "mid: {max_retries: 1}",
        "mid: {litellm_id: a}\npresets: {p: {routes: {zzz: {timeout_s: 1}}}}",
    ],
)
def test_invalid_files_rejected(tmp_path, body):
    f = tmp_path / "r.yaml"
    f.write_text(body)
    with pytest.raises(ConfigError):
        load_registry(f, env={})
