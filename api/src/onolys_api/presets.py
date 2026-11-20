"""Preset allowlist + STT resolution for `POST /sessions` (PRD R2, D8).

Users pick only a preset *name*. Its `stt` is a key into stt_providers.yaml, resolved once
through SP01 `select_stt`; the result is stored on the session. Provider and model names are
never written here.
"""

from pathlib import Path

from onolys_core.errors import InputError
from onolys_core.llm.routes import (
    DEFAULT_PRESET_ENV,
    RouteRegistry,
    default_preset_name,
    load_registry,
    resolve_preset,
)
from onolys_core.stt.select import STT_FILE_NAME, load_stt_config, locate_config_file, select_stt

from onolys_api.config import Settings
from onolys_api.repo.models import SttInfo


class UnknownPreset(Exception):
    pass


class PresetResolver:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._registry: RouteRegistry | None = None
        self._stt_config: dict | None = None

    def _load(self) -> tuple[RouteRegistry, dict]:
        if self._registry is None or self._stt_config is None:
            s = self._settings
            routes = Path(s.routes_file) if s.routes_file else None
            registry = load_registry(routes)
            stt_path = None
            if routes is not None and (routes.parent / STT_FILE_NAME).is_file():
                stt_path = routes.parent / STT_FILE_NAME
            self._stt_config = load_stt_config(stt_path or locate_config_file())
            self._registry = registry
        return self._registry, self._stt_config

    def resolve(self, preset: str | None, language: str) -> tuple[str, SttInfo]:
        """(preset name, stt info). Unknown preset -> UnknownPreset."""
        registry, stt_config = self._load()
        env = {DEFAULT_PRESET_ENV: self._settings.default_preset}
        name = preset or default_preset_name(env)
        try:
            _, stt_key = resolve_preset(name, registry, env)
        except InputError:
            raise UnknownPreset(name) from None
        params = select_stt(stt_key, language, config=stt_config)
        return name, SttInfo(provider=params.provider, model=params.model, language=params.language)
