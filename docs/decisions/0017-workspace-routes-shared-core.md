# 0017. uv workspace, model routes and a shared `onolys_core`

**Audience:** contributors.

**Status:** accepted. Gate results below are pending.

**Context.** The platform (protocol audit, evaluation, API) needs the LLM client, speech-to-text and transcript types that lived inside `eaudit`, and `eval/` may not import `eaudit`. Model choice was three env vars with Anthropic-only quirks in the client, and no STT code existed. The owner widened the mission to the platform scope on 2026-11-20 (see [mission](../mission.md)).

**Decision.**

- **Workspace.** `eaudit/` moves to `engines/eaudit/`. A root virtual `pyproject.toml` declares a uv workspace (members `engines/*`, `api`, `admin/*`; `eval` excluded) with one root `uv.lock`. `eval/` stays standalone and talks to the backend over HTTP only. CI runs `uv sync --frozen --package <name>` from the root.
- **Shared core.** New package `engines/core` (dist `onolys-core`, import `onolys_core`) holds the LLM client and route registry, the provider-neutral STT interface with a Chirp 3 adapter, transcript types, the engine interface, `RunInfo`, PHI-safe logging and retry. `eaudit` imports from it; there are no re-export shims. The `stt-google` extra keeps the Google client out of the default install.
- **Routes.** A YAML route registry (packaged default, or the file named by `ROUTES_FILE`; `DEFAULT_PRESET` picks a preset) replaces the three tier env vars. Route names equal the old tiers (`cheap`, `mid`, `strong`) so recorded fixtures stay valid; task routes are aliases. Provider quirks (`structured_output_mode`, `caching_mode`, `supports_temperature`, `extra_params`) are per-route data. Swapping a model or provider is a YAML edit or one small adapter. Default routes are Claude Sonnet via the Anthropic API. See [llm-client](../implementation/llm-client.md).
- **Env prefix.** `IAUDIT_*` stays for engine and eval settings; platform deploy config is unprefixed.
- **Live gate.** `python -m onolys_core.llm.smoke --preset default` and `python -m onolys_core.stt.check --audio <ref> --preset default` run before paudit work starts; the results go in the section below.
- **STT location.** `us` multi-region; no data-residency claim is made.

**Alternatives.** Per-package path dependencies with separate locks; keeping `eaudit.llm` with shims; env-var-only model config. Each costs more consistency or a second cleanup pass.

**Consequences.** One lock for all Python packages. Core is importable by four consumers and may not import any engine (boundary test). The sample route config is proven only by the live gate.

## Gate result

Pending: filled in when the live checks run with credentials and a 2-speaker sample of at least 10 minutes.

| Item | Result |
|---|---|
| LLM smoke (`onolys_core.llm.smoke`) | pending |
| STT check (`onolys_core.stt.check`) | pending |
| (a) Are word time offsets present? | pending |
| (b) Does diarization work with `language: auto`? | pending |
| (c) p95 latency for 25 minutes of audio | pending |

If (a) is no: use another STT model or provider through the adapter. If (b) is no: default language becomes `en-US` and `auto` leaves the web language list. If (c) exceeds the transcribe poll window (about 20 minutes): another model or provider as in (a).
