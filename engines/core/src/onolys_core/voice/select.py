"""Voice config loading and selection (ai-interview PRD R3, D16): one yaml file.

Located like `stt_providers.yaml`: env VOICE_PROVIDERS_FILE (explicit path), else
`voice_providers.yaml` next to the file named by ROUTES_FILE, else the packaged default.
Never imports a concrete provider.
"""

import os
from importlib import resources
from pathlib import Path

import yaml

from onolys_core.errors import ConfigError, InputError
from onolys_core.voice import VoiceParams

VOICE_FILE_NAME = "voice_providers.yaml"
DEFAULT_RESOURCE = "voice_providers.default.yaml"


def locate_config_file(
    name: str = VOICE_FILE_NAME,
    default_resource: str = DEFAULT_RESOURCE,
    package: str = "onolys_core.voice",
) -> Path:
    explicit = os.environ.get("VOICE_PROVIDERS_FILE")
    if explicit:
        return Path(explicit)
    routes = os.environ.get("ROUTES_FILE")
    if routes:
        candidate = Path(routes).parent / name
        if candidate.is_file():
            return candidate
    return Path(str(resources.files(package).joinpath(default_resource)))


def validate_voice_config(data: dict) -> dict:
    providers = data.get("providers")
    if not isinstance(providers, dict) or not providers:
        raise ConfigError("voice providers file has no `providers`")
    voices = data.get("voices")
    if not isinstance(voices, list) or not voices or not all(isinstance(v, str) for v in voices):
        raise ConfigError("voice providers file has no `voices` list")
    default = data.get("default")
    if default not in providers:
        raise ConfigError(f"voice `default` {default!r} is not a key in `providers`")
    for key, entry in providers.items():
        if not isinstance(entry, dict):
            raise ConfigError(f"voice provider {key!r} must be a mapping")
        for field in ("provider", "model", "voice"):
            if not entry.get(field):
                raise ConfigError(f"voice provider {key!r} is missing `{field}`")
        if entry["voice"] not in voices:
            raise ConfigError(f"voice provider {key!r} default voice not in `voices`")
        if "options" in entry and not isinstance(entry["options"], dict):
            raise ConfigError(f"voice provider {key!r} `options` must be a mapping")
    return data


def load_voice_config(path: Path | None = None) -> dict:
    data = yaml.safe_load((path or locate_config_file()).read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise ConfigError("voice providers file must be a mapping")
    return validate_voice_config(data)


def allowed_voices(config: dict | None = None) -> list[str]:
    return list((config if config is not None else load_voice_config())["voices"])


def select_voice(
    provider_key: str | None = None,
    voice: str | None = None,
    language: str | None = None,
    *,
    system_prompt: str = "",
    resumption_handle: str | None = None,
    config: dict | None = None,
) -> VoiceParams:
    """Build VoiceParams for the default (or named) provider; reject an unlisted voice."""
    cfg = config if config is not None else load_voice_config()
    key = provider_key or cfg["default"]
    entry = cfg["providers"].get(key)
    if entry is None:
        raise InputError(f"unknown voice provider key {key!r}")
    chosen = voice or entry["voice"]
    if chosen not in cfg["voices"]:
        raise InputError(f"unknown voice {chosen!r}")
    return VoiceParams(
        provider=entry["provider"],
        model=entry["model"],
        voice=chosen,
        language=language or "en-US",
        system_prompt=system_prompt,
        resumption_handle=resumption_handle,
        options=dict(entry.get("options") or {}),
    )
