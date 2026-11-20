---
status: draft
summary: Move eaudit/ to engines/eaudit/ with zero behaviour change, extract shared engines/core/ (onolys_core: LLM routes, STT interface + Chirp 3, transcript types, engine interface, run_info, PHI-safe logging, retry) as a uv workspace, and widen mission.md/AGENTS.md to the MITI platform scope.
date: 2026-11-20
---
# PRD: SP01 core — `engines/` move and shared `onolys_core`

Repo/branch: Onolys/onolys (local `iaudit`) / `feat/miti-platform` · Depends on: none (Phase 1) · Owns: `eaudit/` → `engines/eaudit/` (all), new `engines/core/**`, root `pyproject.toml` + `uv.lock`, `.github/workflows/{ci,nightly}.yml`, `scripts/{dev.sh,README.md}`, `README.md`, `AGENTS.md`, `docs/mission.md`, path fixes in `docs/**` and `eval/tests/**`, `docs/decisions/0017-*`

## TL;DR
Two PRs. **PR-A (pure move):** `git mv eaudit engines/eaudit`, fix every path, CI green, nothing else changes. **PR-B (extract):** new `engines/core/` workspace package `onolys_core` holds the LLM client + model-route registry, STT interface, transcript types, engine interface, run_info helpers, PHI-safe logging, retry. eaudit imports from core; its API, fixtures, prompts and tests are unchanged. Docs and mission widen to evidence + protocol (+ later clinician) audit.

## Problem
- paudit (SP02), evaluation (SP03) and api (SP04) need the LLM client, STT and transcript types; today they live inside `eaudit`, and `eval/` is barred from importing eaudit. [verified: eval/tests/test_contracts.py::test_no_backend_import_in_eval]
- Model choice is three env vars (`model_cheap/mid/strong`) with Anthropic-only quirks hard-coded in the client (`thinking: disabled`, ephemeral `cache_control`). [verified: litellm_client.py:`_kwargs`] Swapping to Gemini is not config-only.
- No STT code exists. [verified: grep -ri 'chirp\|speech' eaudit/src → 0 matches]
- `docs/mission.md` and `AGENTS.md` forbid scoring and protocol review. [verified: AGENTS.md line 3; mission.md "No interview administration or protocol review"]

## Goals / Non-Goals
**Goals:** one `engines/` home; shared core usable by 4 consumers; Claude↔Gemini and STT provider/model/language swaps are config; today's eaudit behaves identically (same fixture keys, same `POST /v1/audit`, same tests).
**Non-goals:** paudit/pack code (SP02), rating validation/tips (SP03), API/jobs/storage (SP04), GCP resources (SP06), admin deploy (SP07); changing the eaudit contract (SP03 later adds the optional `profile`, schema `0.0.2`), prompts or 17 checks; renaming `iaudit_eval` or `IAUDIT_*`; provider quality tuning (Claude Sonnet quality is measured in SP02/SP03 on Tejit's transcripts; Gemini/Vertex is at most an optional future route).

## Requirements
**R1 Move (PR-A).** `git mv eaudit engines/eaudit` (history kept). Fix, all verified by grep (52 non-historical files contain `eaudit/`; most are docs):
| Where | Change |
|---|---|
| `ci.yml` job `eaudit` | `working-directory: engines/eaudit`, `cache-dependency-glob` (see D1) |
| `nightly.yml` | same two keys |
| `engines/eaudit/src/eaudit/contract.py:45` | `parents[3]` → `parents[4]` (repo root for `docs/contracts`); comment fixed |
| `eval/tests/{test_scoring_boundaries,test_synthetic_dataset,test_scoring,…}.py` | `repo/"eaudit/eval"` → `repo/"engines/eaudit/eval"`, prompts path, dataset-root strings |
| `eaudit/eval/{run.py,leakage.toml,README.md,build_adhd.py}`, `eaudit/README.md` | path comments/docstrings |
| `scripts/dev.sh:130`, `scripts/README.md` | `uv run --package eaudit uvicorn eaudit.app:app` from `engines/eaudit` |
| `README.md`, `AGENTS.md`, `docs/{architecture,reference,testing,implementation,examples}/**`, `eval/README.md` | link/path text only |
Unchanged (verified): `frontend/vite.config.ts` proxies only `/eval-api` → :8100 and aliases `../docs/contracts`, `../eval/api`; `frontend/src/**` hits of `eaudit` are product ids, not paths. `eval/src` has no eaudit path or import (talks via `IAUDIT_BACKEND_URL`). Historical `docs/agent_files/**` not edited.

**R2 `onolys_core` package (PR-B).** `engines/core/src/onolys_core/`:
| Module | Content | Moved from |
|---|---|---|
| `llm/{types,errors,litellm_client,fixture_client}.py` | `LLMClient` Protocol, `LLMRequest/Result/Usage`, `MetricsCollector`, errors, `LiteLLMClient`, `Fixture/Recording/Stub/FailingClient`, `make_client` | `eaudit/llm/*` |
| `llm/routes.py` + `routes.default.yaml` | route registry (R3) | new |
| `stt/{base,google_chirp,fixture,providers}.py` | R4 | new |
| `transcript.py` | `Turn`, `Transcript`, `Span` (R5) | new |
| `engine.py` | `Engine` protocol, `EngineResult` (R6) | new |
| `run_info.py` | `RunInfo` model + `hash_files()`; no prompt knowledge | split from `eaudit/run_info.py` |
| `safe_log.py` | allowlist logger (R7) | `eaudit/safe_log.py` |
| `retry.py` | `retry()` unchanged | `eaudit/utils/retry.py` |
| `locate.py` | `locate(text, quote, hint)` + normalisation (NFC, case-fold, whitespace collapse; exact → normalised → guarded fuzzy; code-point offsets), needed by SP02 and SP03 | `eaudit/assembler/locate.py` (shim left) |
| `errors.py` | `OnolysError` base, `InputError`, `PackError` (typed; SP02/SP04 map them to results/HTTP) | new |
`eaudit.llm`, `eaudit.safe_log`, `eaudit.utils.retry`, `eaudit.assembler.locate` stay as one-line re-export shims in PR-B (43 files import `eaudit.llm`, 10 `safe_log`, 5 `utils` [verified: grep]); imports are rewritten to `onolys_core` in a later cleanup task, not required for green. Core must never import `eaudit`, `paudit`, `api` (enforced by a test, mirroring the eval boundary test). `eaudit.config.Settings` stays in eaudit; it builds the `LLMConfig` core consumes.

**R3 Model-route registry.** Config file (YAML; default shipped in core; override path env `ROUTES_FILE`, with `IAUDIT_LLM_ROUTES_FILE` kept as an alias; deployed environments point it at `config/{env}/routes.yaml`, SP06 R14). Each route name (the tiers `cheap|mid|strong` remain valid names; engines add their own, e.g. SP03's `parse` and `tips`; SP02 maps its `tiers{code,globals}` params to `mid`/`strong` by default):
```yaml
cheap:
  litellm_id: anthropic/claude-sonnet-5-5   # r6: every shipped default route is Claude Sonnet; swap any route by editing this file
  provider: anthropic            # anthropic | vertex_ai | openai | …
  structured_output_mode: json_object   # json_object | json_schema | tool_call
  caching_mode: anthropic_ephemeral     # anthropic_ephemeral | none | provider_implicit
  region: us                     # e.g. us-central1 for Vertex
  phi_allowed: true
  extra_params: {thinking: {type: disabled}}   # provider quirks live here, not in code
```
**Default routes (r6).** `cheap`, `mid`, `strong` and every engine-added route (`tips`, etc.) all default to `anthropic/claude-sonnet-5-5` through the existing LiteLLM client; the Anthropic API is called directly with `ANTHROPIC_API_KEY` (Secret Manager in deploy, env var locally). Google is used for speech-to-text only; Gemini/Vertex stays an optional future route (the `vertex_ai` route format keeps working) and nothing in v1 defaults to it. `caching_mode: anthropic_ephemeral` stays on so engines can cache shared prefixes (pack + transcript) across calls and N runs. Swapping a model stays a config edit. [RESOLVED: Claude Sonnet for all LLM work (Tejit 2026-11-20 r6)]
`LLMRequest.tier` becomes "route name" (type `str`, same values today, so fixture keys `tier|call_tag|…` stay byte-identical). Back-compat: `IAUDIT_MODEL_CHEAP/MID/STRONG` and `IAUDIT_LLM_RESPONSE_FORMAT` override the default route's `litellm_id` / `structured_output_mode`. Client reads mode, caching and `extra_params` from the route, so a Gemini route is a YAML edit. `phi_allowed=false` routes are rejected at startup when `IAUDIT_PHI_MODE=1` (default off; Tejit owns legal). `run_info.models` reports route → `litellm_id`. **Presets.** The same file may carry a top-level `presets:` map, each preset a named bundle `{routes: {route_name: <route overrides>}, stt: {provider, model, location?}}`; env `DEFAULT_PRESET` (default `default`) names the preset used when a caller names none. The preset names in the file are the allowlist SP04 exposes to users (`preset` param, `GET /v1/presets`); users never pass raw routes or STT params. Core exposes `resolve_preset(name) -> (routes view, SttParams)`; an unknown name raises `InputError`. [RESOLVED: presets live in the routes file, default chosen by `DEFAULT_PRESET` (reconcile pass)]

**R4 STT interface (core).**
```python
class SttParams(BaseModel):
    provider: str = "google"; model: str = "chirp_3"
    recognition: str = "standard"   # r6: standard recognition (not dynamic batch)
    language: str = "auto"          # BCP-47 or "auto"
    diarization: bool = True; speakers: int = 2
    location: str = "us"           # Chirp 3 is offered in multi-regions us/eu, not us-central1 (SP06 R3); env STT_LOCATION / STT_ENDPOINT override
async def transcribe(audio_uri: str, params: SttParams) -> Transcript   # turns carry speaker label + start_ms/end_ms
```
Adapters: `GoogleChirp3` (Speech-to-Text v2, recognizer location `us` multi-region via endpoint `us-speech.googleapis.com`, `gs://` URIs, standard (not dynamic-batch) recognition (long audio via `BatchRecognize` with the default processing strategy, since sync `Recognize` is capped at about 1 min; confirm in the spike), diarization config min/max speakers = `speakers`, ADC auth, no keys in code); `FixtureStt` (replays recorded `Transcript` JSON by audio-uri hash; used by tests, api stub, CI). Per-language provider map in `stt/providers.yaml` (override path env `STT_PROVIDERS_FILE`; deployed: `config/{env}/stt_providers.yaml`; `default: {provider, model}`, `by_language: {xx: {…}}`) so Whisper+diarizer can be added later as an adapter without touching callers. Word-level diarized output is merged into turns by speaker change; adapter never invents speakers or timestamps (mission rule).

**R5 Transcript types.** `Turn{id, speaker:str|None, text, start_ms:int|None, end_ms:int|None, role:str|None, language:str|None}`, `Transcript{turns, language, duration_ms, stt_run:dict}`, `Span{turn_id, start, end}` (code-point offsets, ADR 0002). `eaudit.models.audit.Turn` (API contract, `timestamp: str`, extra=forbid) is NOT replaced; core ships `Transcript.from_eaudit_turns()/to_eaudit_turns()` helpers (ms ↔ `"mm:ss"` string) so api can feed STT output to eaudit.

**R6 Engine interface.**
```python
class Engine(Protocol):
    name: str                      # "eaudit" | "paudit" | "caudit"
    async def run(self, transcript: Transcript, pack: PackRef | None, params: dict, ctx: RunContext) -> EngineResult
class EngineResult(BaseModel): result: BaseModel; run_info: RunInfo
class RunContext: llm: LLMClient; metrics: MetricsCollector; deadline: float | None; request_id: str
class PackRef(BaseModel): id: str; version: str; path: str   # SP02 defines pack contents
```
`engines/eaudit` gains a thin `EauditEngine` wrapper over today's pipeline. Its `params` accept the optional request `profile` (`{suppress_concerns, context_note}`, SP03 R3) and pass it to the eaudit request unchanged; absent = today's code path. The `profile` field, contract `0.0.2` and the suppression filter are added by SP03 (additive edits in `engines/eaudit/`); SP03 maps ratings onto the existing `Section` input, so there is no new 'rating item' input type. [RESOLVED: wrapper accepts optional `profile` (reconcile pass)] `POST /v1/audit` is untouched and does not go through it. Typed results are per-engine pydantic models; core defines no scoring types.

**R7 PHI-safe logging.** `onolys_core.safe_log` keeps the allowlist + blocked name parts (`text, body, transcript, excerpt, message`) and 200-char cap; logger name stays `"iaudit"` (tests use it [verified: 9 `logger="iaudit"` hits]). Base allowlist is generic (request ids, status, counts, tokens, latency, models); engines add theirs via `register_fields(frozenset)` (eaudit registers today's list, so output is identical). New generic fields for STT/jobs: `audio_ms, stt_provider, stt_model, language, speakers, job_id, step`. Audio URIs, transcript text, ratings are never loggable. Unit test: every blocked pattern dropped; a log of a full STT call contains no text.

**R8 Workspace + packaging.** Root `pyproject.toml` (virtual) with `[tool.uv.workspace] members = ["engines/*", "api", "admin/*"], exclude = ["eval"]`; one root `uv.lock` (members over time: `engines/{core,eaudit}`, then `engines/{paudit,evaluation}` (SP02/SP03), `api` (SP04), `admin/{auth,backend}` (SP07)). `engines/eaudit` depends on `onolys-core = { workspace = true }`. `eval/` stays standalone with its own `uv.lock` (its boundary test forbids importing engines). The eval harness is not a v1 priority and may break: fix it if cheap, otherwise disable or skip the eval-related CI jobs that block; do not hack around it. [RESOLVED (Tejit 2026-11-20 r6)] CI: `uv sync --frozen --package eaudit` etc. from repo root; cache glob `uv.lock`. Core optional extra `stt-google` (`google-cloud-speech`) keeps the eaudit install light.

**R9 Docs and mission.** `docs/mission.md`: add "Platform scope" (evidence audit = eaudit; protocol audit = paudit, scoring and protocol review against a protocol pack; clinician audit = caudit, future); replace "Our boundaries / No interview administration or protocol review" and the "does not … assign scores" lines with a scoped version stating those are now in scope per Tejit 2026-11-20 but live in other engines; the 17-check list and eaudit's "not a clinical-correctness judge" stance stay verbatim. `AGENTS.md` line 3 rewritten likewise; docs table gains `engines/`. New ADR 0017 (workspace, routes, shared core). `docs/implementation/llm-client.md` repathed + routes section.

## Architecture
```
api/ ─┐                       protocols/<pack>
paudit ┼─> onolys_core <──────┤ (data, read by engines)
eaudit ┘   llm(routes) · stt · transcript · engine · run_info · safe_log · retry
eval/  ── HTTP only ──> api / eaudit   (no imports)
```
Data flow for the platform: `audio_uri → stt.transcribe → Transcript → Engine.run(transcript, pack, params, ctx) → EngineResult`. LLM calls always via `ctx.llm.complete_json(LLMRequest(tier=<route>))`; deterministic code validates (ADR 0005).

## Decisions
| # | Decision | Choice | Alternatives | Why |
|---|---|---|---|---|
| D1 | Packaging | uv workspace (root lock) | Path deps with per-package locks | One lock for api image + engines; consistent versions; CI invokes `--package`. Cost: lock moves to root, `exclude=["eval"]` needed |
| D2 | Package/dist names | dist `onolys-core`, import `onolys_core` | `core` (collides generically) | Unambiguous on `sys.path` |
| D3 | PR split | PR-A move only, PR-B extract | One PR | Move diff is reviewable by `git mv` similarity; bisectable |
| D4 | Shims | Keep `eaudit.llm/safe_log/utils` re-exports | Rewrite ~58 imports now | Zero-risk green; cleanup later |
| D5 | Env prefix | Keep `IAUDIT_*` for engine/eval settings; prefix is one constant in core. Platform deploy config (api, infra: `ENV`, `ROUTES_FILE`, `STT_PROVIDERS_FILE`, `DEFAULT_PRESET`, …) is unprefixed per SP04/SP06 | `ONOLYS_*` + fallback | `eval`, `vite.config.ts`, docs, scripts use it; rename is cosmetic and costs a back-compat layer; revisit later [DEFERRED] |
| D6 | Route file format | YAML + env overrides for the 3 tiers | Env vars only; JSON | Per-route quirks (`extra_params`) need structure; env keeps today's deploys working |
| D7 | Core `Turn` vs eaudit `Turn` | Separate; convert helpers | Replace eaudit's | Contract 0.0.1 `extra=forbid`; zero behaviour change |
| D8 | eval ↔ engines | Stay decoupled (HTTP) | eval imports core | Existing boundary test; no change to eval deps |

## Manual steps
- Branch protection: none today [verified: `gh api …/branches/main/protection` → 404 "Branch not protected"]. If Tejit adds required checks, job names `eaudit` and `frontend` must be kept (this PRD keeps them).
- Tejit: confirm Speech-to-Text v2 API enabled on project `onolys` and Chirp 3 usable in the `us` multi-region (SP06 R3); ADC quota project must be `onolys` (brief: currently `juno-medical-clarity`).
- Tejit adds the Anthropic API key (`ANTHROPIC_API_KEY`) to Secret Manager (SP06 R10); every default LLM route needs it.
- Tejit supplies a short 2-speaker audio sample for the Chirp 3 diarization check.

## Risks / Open Questions
- [RESOLVED: standard (non-dynamic-batch) recognition; cost not a concern (Tejit 2026-11-20 r6)] The dynamic-batch pricing / `chirp_3` diarization question is moot.
- [RESOLVED: STT location `us` multi-region (reconcile pass); data-residency claims dropped (Tejit 2026-11-20 r6)] Chirp 3 is only documented for `us`/`eu` multi-regions (SP06 R3); no residency claim is made; recorded in ADR 0017 and SP06's ADR.
- [RESOLVED: eval may break; fix if cheap, otherwise disable/skip the eval CI job; not a hack priority (Tejit 2026-11-20 r6)] `uv` behaviour for an excluded standalone `eval/` under a workspace root; verify with `uv sync --project eval` before merging PR-A/B (fallback: D1 alternative, path deps). Also confirm uv tolerates member paths that do not exist yet (`api`, `admin/*`); else add each member as its SP lands.
- [RESOLVED: default LLM is Claude Sonnet via the Anthropic API with today's json_object/tool_call modes; `json_schema` for Gemini on Vertex is an optional future route, not evaluated in v1 (Tejit 2026-11-20 r6)] SP01 still ships the `json_schema` switch.
- [RESOLVED: no change needed] frontend dev proxy and `vite.config.ts` have no `eaudit/` paths.
- [RESOLVED: keep] fixture keys use `tier|call_tag|…`; route names equal old tier names so recordings stay valid.
- [DEFERRED] `ONOLYS_*` rename; removal of shims; Whisper adapter; `caudit`.

## Acceptance Criteria
1. `eaudit/` no longer exists; `engines/eaudit/` holds it; `git log --follow` works; `grep -rIn "[^s/]eaudit/src" . --exclude-dir=agent_files` finds no stale path.
2. PR-A: `cd engines/eaudit && uv run pytest -q` passes the same test count as on `main`; `cd frontend && npm test` passes; CI jobs `eaudit`, `frontend` green; `cd eval && uv run pytest -q` and the nightly `eval-oracle` dry-run are best-effort (eval is not a v1 priority; a blocking eval job may be disabled/skipped).
3. PR-B: same eaudit tests pass untouched (only shims added); fixture-replay tests need no re-recording; `POST /v1/audit` response for a recorded example is byte-identical to before.
4. `onolys_core` imports with no eaudit/paudit/api import (boundary test); `uv run --package onolys-core pytest` covers routes, STT fixture adapter, safe_log, retry.
5. A route file with a Gemini route (`vertex_ai/gemini-…`, `json_schema`, `caching_mode: none`, no `thinking`) is accepted and `LiteLLMClient` builds kwargs from it with a fake `acompletion` (test); no code change needed to swap; a `presets:` entry + `DEFAULT_PRESET` select it and `ROUTES_FILE`/`STT_PROVIDERS_FILE` redirect the loaders (tests); every shipped default route resolves to `anthropic/claude-sonnet-5-5` with the key read from `ANTHROPIC_API_KEY`.
6. `FixtureStt` returns a `Transcript` with ≥2 speaker labels and `start_ms/end_ms`; `GoogleChirp3` request builder unit-tested offline (diarization min/max = 2, language `auto` handled, location `us` → endpoint `us-speech.googleapis.com`).
7. A log-capture test shows no transcript/audio text or URI in any core log line.
8. `docs/mission.md` and `AGENTS.md` state the widened scope, keep the 17 checks; `docs/decisions/0017-*` exists; no broken relative links (`grep` link check).
