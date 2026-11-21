"""Optional pack hooks from `rules.py` (PRD R1): `check_input`, `validate_codes`,
`compute_summary`. All optional, pure functions, no I/O. Pack code is trusted (it is covered
by `pack_hash`)."""

import importlib.util
import sys
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from onolys_core import PackError

from paudit.pack import Pack

HOOK_NAMES = ("check_input", "validate_codes", "compute_summary")


@dataclass(frozen=True)
class Hooks:
    check_input: Callable[..., Any] | None = None
    validate_codes: Callable[..., Any] | None = None
    compute_summary: Callable[..., Any] | None = None


def load_hooks(pack: Pack) -> Hooks:
    """Import `rules.py` (if any) and pick up the hooks it defines. Missing ones are None."""
    path = pack.rules_path
    if path is None:
        return Hooks()
    name = f"_paudit_rules_{pack.id}_{pack.pack_hash[:12]}".replace("-", "_")
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise PackError(f"{path.parent.name}/rules.py cannot be imported")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    try:
        spec.loader.exec_module(mod)
    except Exception as exc:
        sys.modules.pop(name, None)
        raise PackError(
            f"{path.parent.name}/rules.py failed to import: {type(exc).__name__}"
        ) from exc
    found: dict[str, Callable[..., Any]] = {}
    for hook in HOOK_NAMES:
        fn = getattr(mod, hook, None)
        if fn is None:
            continue
        if not callable(fn):
            raise PackError(f"rules.py: {hook} is not callable")
        found[hook] = fn
    return Hooks(**found)
