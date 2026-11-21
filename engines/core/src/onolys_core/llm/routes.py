"""Model-route registry and presets (PRD R3, D6, D11, D12).

Model choice is data: a YAML file (packaged default, or the path in env ROUTES_FILE).
Engines ask for a route by name. Back-compat env overrides (applied to the base routes,
before a preset's overrides): IAUDIT_MODEL_CHEAP/MID/STRONG set that route's `litellm_id`;
IAUDIT_LLM_RESPONSE_FORMAT sets `structured_output_mode` on every full route.
"""

import os
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Literal

import yaml

from onolys_core.errors import ConfigError, InputError
from onolys_core.stt.select import locate_config_file

ROUTES_ENV = "ROUTES_FILE"
DEFAULT_PRESET_ENV = "DEFAULT_PRESET"
DEFAULT_PRESET_NAME = "default"
DEFAULT_RESOURCE = "routes.default.yaml"
_MODES = ("json_object", "json_schema")
_CACHING = ("none", "provider_implicit", "anthropic_ephemeral")
_TIER_ENV = {
    "cheap": "IAUDIT_MODEL_CHEAP",
    "mid": "IAUDIT_MODEL_MID",
    "strong": "IAUDIT_MODEL_STRONG",
}
_FORMAT_ENV = "IAUDIT_LLM_RESPONSE_FORMAT"
_FIELDS = {
    "litellm_id",
    "api_key_env",
    "structured_output_mode",
    "caching_mode",
    "supports_temperature",
    "max_output_tokens",
    "context_tokens",
    "timeout_s",
    "max_concurrency",
    "max_retries",
    "backoff_s",
    "extra_params",
}


@dataclass(frozen=True)
class Route:
    litellm_id: str
    api_key_env: str | None = None
    structured_output_mode: Literal["json_object", "json_schema"] = "json_object"
    caching_mode: Literal["none", "provider_implicit", "anthropic_ephemeral"] = "none"
    supports_temperature: bool = True
    max_output_tokens: int = 16000
    context_tokens: int = 1_000_000
    timeout_s: float = 180
    max_concurrency: int = 8
    max_retries: int = 3
    backoff_s: float = 2
    extra_params: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Preset:
    routes: dict[str, dict]
    stt: str | None = None


@dataclass(frozen=True)
class RouteRegistry:
    raw_routes: dict[str, dict]
    presets: dict[str, Preset]

    def routes(self) -> dict[str, Route]:
        return _resolve_all(self.raw_routes)


def routes_path() -> Path:
    env = os.environ.get(ROUTES_ENV)
    if env:
        p = Path(env)
        if not p.is_file():
            raise ConfigError(f"{ROUTES_ENV}={env!r} is not a file")
        return p
    return locate_config_file(DEFAULT_RESOURCE, DEFAULT_RESOURCE, "onolys_core.llm")


def _apply_env(raw: dict[str, dict], env: dict[str, str]) -> dict[str, dict]:
    out = {k: dict(v) for k, v in raw.items()}
    for name, var in _TIER_ENV.items():
        if env.get(var) and name in out and "alias" not in out[name]:
            out[name]["litellm_id"] = env[var]
    fmt = env.get(_FORMAT_ENV)
    if fmt:
        for entry in out.values():
            if "alias" not in entry:
                entry["structured_output_mode"] = fmt
    return out


def load_registry(path: Path | None = None, env: dict[str, str] | None = None) -> RouteRegistry:
    """Parse and validate the routes file, applying back-compat env overrides."""
    env = dict(os.environ) if env is None else env
    src = path or routes_path()
    data = yaml.safe_load(src.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise ConfigError(f"routes file {src} must be a mapping")
    presets_raw = data.pop("presets", None) or {}
    if not isinstance(presets_raw, dict):
        raise ConfigError("`presets` must be a mapping")
    raw = {k: v for k, v in data.items() if not str(k).startswith("_")}
    for name, entry in raw.items():
        if not isinstance(entry, dict):
            raise ConfigError(f"route {name!r} must be a mapping")
    presets = {}
    for pname, p in presets_raw.items():
        p = p or {}
        presets[str(pname)] = Preset(routes=dict(p.get("routes") or {}), stt=p.get("stt"))
    reg = RouteRegistry(_apply_env(raw, env), presets)
    reg.routes()  # validate base
    for pname in presets:
        _resolve_all(_overlay(reg.raw_routes, presets[pname].routes))
    return reg


def _overlay(base: dict[str, dict], overrides: dict[str, dict]) -> dict[str, dict]:
    out = {k: dict(v) for k, v in base.items()}
    for name, ov in overrides.items():
        if name not in out:
            raise ConfigError(f"preset overrides unknown route {name!r}")
        if "alias" in ov:
            out[name] = dict(ov)
            continue
        cur = out[name]
        if "alias" in cur:
            cur = dict(_resolve_entry(out, name))
        out[name] = {**cur, **ov}
    return out


def _resolve_entry(raw: dict[str, dict], name: str) -> dict:
    seen: list[str] = []
    cur = name
    while True:
        if cur not in raw:
            raise ConfigError(f"route {cur!r} not defined (referenced by {name!r})")
        entry = raw[cur]
        if "alias" not in entry:
            return entry
        if cur in seen:
            raise ConfigError(f"alias cycle at route {cur!r}")
        seen.append(cur)
        cur = entry["alias"]


def _build(name: str, entry: dict) -> Route:
    unknown = set(entry) - _FIELDS
    if unknown:
        raise ConfigError(f"route {name!r}: unknown field(s) {sorted(unknown)}")
    if not entry.get("litellm_id"):
        raise ConfigError(f"route {name!r}: `litellm_id` is required")
    route = Route(**entry)
    if route.structured_output_mode not in _MODES:
        raise ConfigError(f"route {name!r}: structured_output_mode must be one of {_MODES}")
    if route.caching_mode not in _CACHING:
        raise ConfigError(f"route {name!r}: caching_mode must be one of {_CACHING}")
    if not isinstance(route.extra_params, dict):
        raise ConfigError(f"route {name!r}: extra_params must be a mapping")
    return replace(route, extra_params=dict(route.extra_params))


def _resolve_all(raw: dict[str, dict]) -> dict[str, Route]:
    return {name: _build(name, _resolve_entry(raw, name)) for name in raw}


def default_preset_name(env: dict[str, str] | None = None) -> str:
    env = os.environ if env is None else env
    return env.get(DEFAULT_PRESET_ENV) or DEFAULT_PRESET_NAME


def resolve_preset(
    name: str | None = None,
    registry: RouteRegistry | None = None,
    env: dict[str, str] | None = None,
) -> tuple[dict[str, Route], str | None]:
    """(routes view, stt key | None). `name` None -> DEFAULT_PRESET. Unknown name: InputError."""
    reg = registry or load_registry(env=env)
    pname = name or default_preset_name(env)
    preset = reg.presets.get(pname)
    if preset is None:
        if pname != DEFAULT_PRESET_NAME:
            raise InputError(f"unknown preset {pname!r}")
        preset = Preset(routes={})
    return _resolve_all(_overlay(reg.raw_routes, preset.routes)), preset.stt


def check_api_keys(routes: dict[str, Route], env: dict[str, str] | None = None) -> None:
    """Startup check: every route's `api_key_env` must be set; the error names the variable."""
    env = os.environ if env is None else env
    missing: dict[str, list[str]] = {}
    for name, r in routes.items():
        if r.api_key_env and not env.get(r.api_key_env):
            missing.setdefault(r.api_key_env, []).append(name)
    if missing:
        parts = [f"{var} (routes: {', '.join(sorted(n))})" for var, n in sorted(missing.items())]
        raise ConfigError("LLM API key environment variable not set: " + "; ".join(parts))


def allowed_presets(registry: RouteRegistry | None = None) -> list[str]:
    reg = registry or load_registry()
    return sorted(reg.presets) or [DEFAULT_PRESET_NAME]


__all__ = [
    "Preset",
    "Route",
    "RouteRegistry",
    "allowed_presets",
    "check_api_keys",
    "default_preset_name",
    "load_registry",
    "resolve_preset",
    "routes_path",
]
