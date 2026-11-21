"""Plain LLM settings consumed by the client. Engines build one from their own settings."""

from dataclasses import dataclass, field
from typing import Literal

from .routes import Route


@dataclass(frozen=True)
class LLMConfig:
    """Model choice, limits and provider quirks live in routes, not here.

    `routes` None: the registry (packaged YAML or ROUTES_FILE) resolved for `preset`
    (None: DEFAULT_PRESET). An engine may pass its own routes to override the file.
    """

    llm_mode: Literal["live", "fixture", "stub"] = "live"
    fixture_dir: str = "tests/fixtures/llm"
    routes: dict[str, Route] | None = field(default=None, compare=False)
    preset: str | None = None
