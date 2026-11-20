"""Staging-only forced-failure presets (SP09 R6, D4, AC7, AC8): config only, no code hooks."""

from pathlib import Path

import pytest
import yaml
from onolys_core.llm.routes import allowed_presets, load_registry, resolve_preset

from onolys_api.config import Settings
from onolys_api.presets import PresetResolver, UnknownPreset

pytestmark = pytest.mark.unit

ROOT = Path(__file__).resolve().parents[2]
STAGING = ROOT / "config/staging/routes.yaml"
PROD = ROOT / "config/prod/routes.yaml"
BROKEN = ("test-broken-llm", "test-broken-eaudit")
ALL = ("cheap", "mid", "strong", "paudit_code", "paudit_globals", "tips")
EAUDIT = ("cheap", "mid", "strong")
TASK = ("paudit_code", "paudit_globals", "tips")


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for v in (
        "ROUTES_FILE", "DEFAULT_PRESET", "IAUDIT_MODEL_CHEAP", "IAUDIT_MODEL_MID",
        "IAUDIT_MODEL_STRONG", "IAUDIT_LLM_RESPONSE_FORMAT",
    ):  # fmt: skip
        monkeypatch.delenv(v, raising=False)


@pytest.fixture(scope="module")
def staging():
    return load_registry(STAGING, env={})


def test_staging_registers_both_presets(staging):
    assert set(BROKEN) <= set(staging.presets) and "default" in staging.presets


def test_broken_llm_points_every_route_at_a_missing_model(staging):
    routes, _ = resolve_preset("test-broken-llm", staging, {})
    good, _ = resolve_preset("default", staging, {})
    for name in ALL:
        assert routes[name].litellm_id != good[name].litellm_id
        assert "does-not-exist" in routes[name].litellm_id


def test_broken_eaudit_breaks_tiers_only(staging):
    routes, _ = resolve_preset("test-broken-eaudit", staging, {})
    good, _ = resolve_preset("default", staging, {})
    for name in EAUDIT:
        assert "does-not-exist" in routes[name].litellm_id
    for name in TASK:
        assert routes[name] == good[name]
        assert "does-not-exist" not in routes[name].litellm_id


def test_broken_eaudit_task_routes_are_full_routes_not_aliases(staging):
    ov = staging.presets["test-broken-eaudit"].routes
    for name in TASK:
        assert "litellm_id" in ov[name] and "alias" not in ov[name]
    # no alias chain from paudit/tips (in the effective table) reaches a broken route
    eff = {**staging.raw_routes, **{k: v for k, v in ov.items()}}
    for name in TASK:
        assert "alias" not in eff[name]
        assert "does-not-exist" not in eff[name]["litellm_id"]


def test_default_preset_on_staging_is_unbroken(staging):
    routes, _ = resolve_preset("default", staging, {})
    assert not any("does-not-exist" in r.litellm_id for r in routes.values())


def test_prod_routes_contain_neither_preset():
    reg = load_registry(PROD, env={})
    assert not set(BROKEN) & set(reg.presets)
    text = PROD.read_text()
    assert "test-broken" not in text and "does-not-exist" not in text
    assert not set(BROKEN) & set(allowed_presets(reg))


def test_runs_preset_check_accepts_staging_presets_and_prod_rejects(tmp_path):
    """POST /runs {preset} and POST /sessions share PresetResolver (registry keys = allowlist)."""
    stg = PresetResolver(Settings(env="test", routes_file=str(STAGING)))
    for name in BROKEN:
        assert stg.resolve(name, "en")[0] == name
    prod = PresetResolver(Settings(env="test", routes_file=str(PROD)))
    for name in BROKEN:
        with pytest.raises(UnknownPreset):
            prod.resolve(name, "en")


def test_staging_yaml_has_no_secrets():
    data = yaml.safe_load(STAGING.read_text())
    assert "sk-" not in STAGING.read_text() and "presets" in data
