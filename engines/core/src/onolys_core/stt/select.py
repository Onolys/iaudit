"""STT selection (PRD R4, D10): one yaml file, no STT env vars.

Precedence: preset stt key -> by_language[lang] -> default. The session language wins
over any language on the entry. Never imports a concrete provider.
"""

import os
from importlib import resources
from pathlib import Path

import yaml

from onolys_core.errors import InputError
from onolys_core.stt import SttParams

STT_FILE_NAME = "stt_providers.yaml"
DEFAULT_RESOURCE = "stt_providers.default.yaml"


def locate_config_file(name: str = STT_FILE_NAME, default_resource: str = DEFAULT_RESOURCE) -> Path:
    """`name` next to the file named by env ROUTES_FILE if present, else the packaged default."""
    routes = os.environ.get("ROUTES_FILE")
    if routes:
        candidate = Path(routes).parent / name
        if candidate.is_file():
            return candidate
    return Path(str(resources.files("onolys_core.stt").joinpath(default_resource)))


def load_stt_config(path: Path | None = None) -> dict:
    data = yaml.safe_load((path or locate_config_file()).read_text(encoding="utf-8")) or {}
    if not isinstance(data.get("providers"), dict) or not data["providers"]:
        raise InputError("stt providers file has no `providers`")
    return data


def select_stt(
    preset_stt_key: str | None, language: str | None = None, *, config: dict | None = None
) -> SttParams:
    cfg = config if config is not None else load_stt_config()
    lang = language or "auto"
    by_language = cfg.get("by_language") or {}
    key = preset_stt_key or by_language.get(lang) or cfg.get("default")
    if not key:
        raise InputError("no STT provider selected and no `default` configured")
    entry = cfg["providers"].get(key)
    if entry is None:
        raise InputError(f"unknown STT provider key {key!r}")
    fields = {k: v for k, v in entry.items() if k != "language"}
    return SttParams(**fields, language=lang)
