"""Live LLM smoke (PRD R11, AC10): one real `complete_json` per route of a preset.

    python -m onolys_core.llm.smoke --preset default

Every route name is exercised, aliases included (e.g. `paudit_code` -> `mid`). A route passes
when the call returns schema-valid JSON. Prints model id, latency and tokens, never a key.
Needs the route's API key env var. Exit code 0 only if every route passes.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from dataclasses import dataclass

from pydantic import BaseModel

from .config import LLMConfig
from .routes import Route, resolve_preset
from .types import LLMClient, LLMRequest

SYSTEM = "You are a connectivity check. Reply with a single JSON object and nothing else."
USER = 'Reply with exactly this JSON object: {"ok": true}'


class SmokeReply(BaseModel):
    ok: bool


@dataclass
class SmokeResult:
    route: str
    ok: bool
    model: str = ""
    latency_ms: float = 0.0
    input_tokens: int = 0
    output_tokens: int = 0
    attempts: int = 0
    error: str = ""


async def smoke_route(client: LLMClient, route: str, routes: dict[str, Route]) -> SmokeResult:
    configured = routes[route].litellm_id
    req = LLMRequest(
        tier=route,
        system=SYSTEM,
        user=USER,
        response_model=SmokeReply,
        call_tag=f"smoke.{route}",
        max_tokens=2000,
        timeout_s=routes[route].timeout_s,
    )
    try:
        res = await client.complete_json(req)
    except Exception as exc:  # report every failure; the run goes on to the next route
        return SmokeResult(route, False, model=configured, error=f"{type(exc).__name__}: {exc}")
    ok = isinstance(res.parsed, SmokeReply)
    return SmokeResult(
        route,
        ok,
        model=res.model or configured,
        latency_ms=res.latency_ms,
        input_tokens=res.usage.input_tokens,
        output_tokens=res.usage.output_tokens,
        attempts=res.attempts,
        error="" if ok else "reply is not a SmokeReply",
    )


async def run_smoke(client: LLMClient, routes: dict[str, Route]) -> list[SmokeResult]:
    """Sequential, one call per route name, in file order."""
    return [await smoke_route(client, name, routes) for name in routes]


def format_results(results: list[SmokeResult]) -> str:
    lines = [f"{'route':<16}{'status':<8}{'model':<36}{'ms':>8}{'in':>8}{'out':>8}  note"]
    for r in results:
        note = r.error or (f"attempts={r.attempts}" if r.attempts > 1 else "")
        lines.append(
            f"{r.route:<16}{'PASS' if r.ok else 'FAIL':<8}{r.model:<36}"
            f"{r.latency_ms:>8.0f}{r.input_tokens:>8}{r.output_tokens:>8}  {note}".rstrip()
        )
    passed = sum(r.ok for r in results)
    lines.append(f"{passed}/{len(results)} routes passed")
    return "\n".join(lines)


def smoke_passed(results: list[SmokeResult]) -> bool:
    return bool(results) and all(r.ok for r in results)


def main(argv: list[str] | None = None, client: LLMClient | None = None) -> int:
    p = argparse.ArgumentParser(prog="python -m onolys_core.llm.smoke", description=__doc__)
    p.add_argument("--preset", default=None, help="preset name (default: DEFAULT_PRESET)")
    args = p.parse_args(argv)
    routes, _ = resolve_preset(args.preset)
    if client is None:
        from . import make_client

        client = make_client(LLMConfig(llm_mode="live", routes=routes, preset=args.preset))
    results = asyncio.run(run_smoke(client, routes))
    print(format_results(results))
    return 0 if smoke_passed(results) else 1


if __name__ == "__main__":
    sys.exit(main())
