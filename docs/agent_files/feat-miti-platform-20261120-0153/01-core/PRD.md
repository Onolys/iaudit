---
status: draft
summary: Move eaudit/ to engines/eaudit/ in one PR (existing tests still pass), extract shared engines/core/ (onolys_core: LLM route registry, provider-neutral STT start/poll interface + Chirp 3 adapter, transcript types, engine interface, run_info, PHI-safe logging, retry) as a uv workspace, add live STT/LLM checks that gate SP02, and widen mission.md/AGENTS.md to the MITI platform scope.
date: 2026-11-20
---
# PRD: SP01 core — `engines/` move and shared `onolys_core`

Repo/branch: Onolys/onolys (local `iaudit`) / `feat/miti-platform` · Depends on: none (Phase 1) · Owns: `eaudit/` → `engines/eaudit/` (all), new `engines/core/**`, root `pyproject.toml` + `uv.lock`, `.github/workflows/{ci,nightly}.yml`, `scripts/{dev.sh,README.md}`, `README.md`, `AGENTS.md`, `docs/mission.md`, path fixes in `docs/**` and `eval/tests/**`, `docs/decisions/0017-*`

## TL;DR
One PR (r7; the two-PR split with shims is cut). **Move:** `git mv eaudit engines/eaudit`, fix every path. **Extract:** new `engines/core/` workspace package `onolys_core` holds the LLM client + model-route registry, a provider-neutral STT interface (`start`/`poll`), transcript types, engine interface, run_info helpers, PHI-safe logging, retry. eaudit imports from core; its API contract, fixtures, prompts and tests still pass (responses may show new model ids). LLM and STT provider/model are swapped by config or one small adapter, never a rewrite. A live STT check + LLM smoke is a gate before SP02 starts. Docs and mission widen to evidence + protocol (+ later clinician) audit.

## Problem
- paudit (SP02), evaluation (SP03) and api (SP04) need the LLM client, STT and transcript types; today they live inside `eaudit`, and `eval/` is barred from importing eaudit. [verified: eval/tests/test_contracts.py::test_no_backend_import_in_eval]
- Model choice is three env vars (`model_cheap/mid/strong`) with Anthropic-only quirks hard-coded in the client (`thinking: disabled`, ephemeral `cache_control`). [verified: litellm_client.py:`_kwargs`] Swapping to Gemini is not config-only.
- No STT code exists. [verified: grep -ri 'chirp\|speech' eaudit/src → 0 matches]
- `docs/mission.md` and `AGENTS.md` forbid scoring and protocol review. [verified: AGENTS.md line 3; mission.md "No interview administration or protocol review"]

## Goals / Non-Goals
**Goals:** one `engines/` home; shared core usable by 4 consumers; LLM provider/model and STT provider/model/language swaps are config or one small adapter, never a rewrite; existing eaudit tests still pass (same fixture keys, same `POST /v1/audit` contract; responses may show new model ids); live checks prove the shipped STT and LLM config before SP02 builds on it.
**Non-goals:** paudit/pack code (SP02), rating validation/tips (SP03), API/jobs/storage (SP04), GCP resources (SP06), admin deploy (SP07); changing the eaudit contract (SP03 later adds the optional `profile`, schema `0.0.2`), prompts or 17 checks; renaming `iaudit_eval` or `IAUDIT_*`; provider quality tuning (Claude Sonnet quality is measured in SP02/SP03 on Tejit's transcripts; Gemini/Vertex is at most an optional future route).

## Requirements
**R1 Move.** `git mv eaudit engines/eaudit` (history kept). Fix, all verified by grep (52 non-historical files contain `eaudit/`; most are docs):
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

**R2 `onolys_core` package.** `engines/core/src/onolys_core/`:
| Module | Content | Moved from |
|---|---|---|
| `llm/{types,errors,litellm_client,fixture_client}.py` | `LLMClient` Protocol (one `complete_json`), `LLMRequest/Result/Usage`, `MetricsCollector`, errors (+ new `LLMRateLimited`), `LiteLLMClient`, `Fixture/Recording/Stub/FailingClient`, `make_client` | `eaudit/llm/*` |
| `llm/routes.py` + `routes.default.yaml` | route registry (R3) | new |
| `llm/{warm,smoke}.py` | `warm_then_fanout()` helper (R3); live LLM smoke (R11) | new |
| `stt/{base,google_chirp,fixture,select,check}.py` + `stt_providers.default.yaml` | R4; live STT check (R11) | new |
| `transcript.py` | `Turn`, `Transcript`, `Span` (R5) | new |
| `engine.py` | `Engine` protocol, `EngineResult` (R6) | new |
| `run_info.py` | `RunInfo` model (R10) + `hash_files()`; no prompt knowledge | split from `eaudit/run_info.py` |
| `safe_log.py` | allowlist logger (R7) | `eaudit/safe_log.py` |
| `retry.py` | `retry()` unchanged | `eaudit/utils/retry.py` |
| `locate.py` | `locate(text, quote, hint)` + normalisation (NFC, case-fold, whitespace collapse; exact → normalised → guarded fuzzy; code-point offsets), needed by SP02 and SP03 | `eaudit/assembler/locate.py` |
| `errors.py` | `OnolysError` base, `InputError`, `PackError` (typed; SP02/SP04 map them to results/HTTP) | new |
Imports of `eaudit.llm`, `eaudit.safe_log`, `eaudit.utils.retry`, `eaudit.assembler.locate` are rewritten to `onolys_core` in the same PR (mechanical; 43 files import `eaudit.llm`, 10 `safe_log`, 5 `utils` [verified: grep]); no re-export shims are left (r7). Core must never import `eaudit`, `paudit`, `api` (enforced by a test, mirroring the eval boundary test). `eaudit.config.Settings` stays in eaudit; it builds the `LLMConfig` core consumes.

**R3 Model-route registry.** Config file (YAML; default shipped in core; override path env `ROUTES_FILE`; deployed environments point it at `config/{env}/routes.yaml`, SP06 R14). There is one `LLMClient.complete_json`; engines ask for a route by name and never branch on provider and never hold model ids, token limits or timeouts: those come from the route. Route names: eaudit's existing `cheap|mid|strong`, plus task-named routes `paudit_code`, `paudit_globals` (SP02) and `tips` (SP03). A task route is either a full route or `{alias: <route>}`; shipped default is `alias: mid`.
```yaml
mid:                                        # cheap and strong carry the same fields
  litellm_id: anthropic/claude-sonnet-5-5   # every shipped default route is Claude Sonnet; swap any route by editing this file
  api_key_env: ANTHROPIC_API_KEY            # startup fails with a clear error naming the variable if it is unset
  structured_output_mode: json_object       # json_object | json_schema
  caching_mode: anthropic_ephemeral         # none | provider_implicit | anthropic_ephemeral
  supports_temperature: false               # client omits `temperature` for this route
  max_output_tokens: 16000                  # explicit and generous: today's code default (1024) is too small for coding batches
  context_tokens: 1000000
  timeout_s: 180                            # today's code default is 30
  max_concurrency: 8                        # one process-wide semaphore per route
  max_retries: 3                            # default 3
  backoff_s: 2                              # default 2; exponential with jitter, honours retry-after
  extra_params: {}                          # provider quirks live here, not in code
paudit_code:    {alias: mid}
paudit_globals: {alias: mid}
tips:           {alias: mid}
```
**Sample route, what is verified (r7).** Checked against Anthropic's API reference for `claude-sonnet-5-5` (via the `claude-api` skill, 2026-11-20): `thinking: {type: disabled}` returns 400, so the old `extra_params: {thinking: {type: disabled}}` is removed and `thinking` is not sent (the model then runs adaptive thinking; the only accepted thinking-off form is `{type: between_tools}`, not set here); a non-default `temperature` returns 400, hence `supports_temperature: false`; forced `tool_choice` (`any`/`tool`) returns 400, hence no forced-tool structured mode; assistant prefill returns 400; context window 1M tokens; output cap 128K tokens, but large values need streaming, so the non-streaming client keeps 16,000 (thinking shares that budget). Not verified: how LiteLLM implements `json_object` for this model and whether it passes these fields through unchanged. The live LLM smoke (R11, AC10) is what proves each route's config; if `json_object` fails there, the route moves to `json_schema`, a YAML edit.
**Default routes.** `cheap`, `mid`, `strong` and every task route all resolve to `anthropic/claude-sonnet-5-5` through the existing LiteLLM client; the Anthropic API is called directly with the key named by the route's `api_key_env` (Secret Manager in deploy via SP06's `llm_secrets` map, env var locally). Google is used for speech-to-text only; Gemini/Vertex stays an optional future route (the `vertex_ai/…` id format keeps working; Vertex-only settings such as location go under `extra_params`) and nothing in v1 defaults to it. Swapping a model stays a config edit. [RESOLVED: Claude Sonnet for all LLM work (Tejit 2026-11-20 r6)]
**Client behaviour (all driven by the route, r7).**
- `LLMRequest.tier` becomes "route name" (type `str`, same values today, so fixture keys `tier|call_tag|…` are unchanged). `LLMRequest.max_tokens` / `timeout_s` become optional: absent = the route's `max_output_tokens` / `timeout_s`; a larger request value is clamped to the route's. A response cut off at the token limit raises `LLMBadOutput`.
- `temperature` is omitted from the call when `supports_temperature` is false. Engines do not set sampling parameters; repeated runs rely on natural variance and determinism is not promised.
- `cache_prefixes` are always prompt content. With `caching_mode: none|provider_implicit` the client joins prefixes + system into one string; with `anthropic_ephemeral` it sends them as annotated cache blocks. An engine never checks which one applies.
- **Prompt caching and parallel calls.** Parallel calls cannot read a cache entry that is still being written. Core ships `llm/warm.py::warm_then_fanout(first, rest)`: send one call, wait for it, then fan out the rest (the existing `eaudit/pipeline/warmup.py` pattern). No doc or estimate may assume cache reuse across simultaneous calls.
- **Retries and rate limits.** `max_retries` / `backoff_s` apply to timeouts, unavailable and bad output. New error class `LLMRateLimited` (HTTP 429/529) always backs off (exponential with jitter, honours `retry-after`) and retries for as long as the request deadline allows; it does not use up `max_retries`. One process-wide semaphore per route, sized `max_concurrency`, replaces the single global one.
- `structured_output_mode`, caching and `extra_params` are read from the route, so a Gemini route is a YAML edit. Back-compat: `IAUDIT_MODEL_CHEAP/MID/STRONG` and `IAUDIT_LLM_RESPONSE_FORMAT` override the matching route's `litellm_id` / `structured_output_mode`.

**Presets.** The same file may carry a top-level `presets:` map, each preset a named bundle `{routes: {route_name: <route overrides>}, stt: <key in stt_providers.yaml>}` (the STT entry itself is defined only in `stt_providers.yaml`, R4); env `DEFAULT_PRESET` (default `default`) names the preset used when a caller names none. The preset names in the file are the allowlist SP04 exposes to users (`preset` param, `GET /v1/presets`); users never pass raw routes or STT params. Core exposes `resolve_preset(name) -> (routes view, stt key | None)`; an unknown name raises `InputError`. A preset's `stt` applies at session creation only; a re-run with another preset changes LLM routes only. [RESOLVED: presets live in the routes file, default chosen by `DEFAULT_PRESET` (reconcile pass)]

**R4 STT interface (core).**
```python
class SttParams(BaseModel):
    provider: str; model: str           # filled from the selected stt_providers.yaml entry
    language: str = "auto"              # BCP-47 or "auto"
    diarization: bool = True; speakers_min: int = 2; speakers_max: int = 2
    options: dict = {}                  # provider-only fields; Google: recognition, location, endpoint
class AudioRef(BaseModel): uri: str; local_path_fn: Callable[[], Path] | None; mime: str; duration_ms: int | None
class Word(BaseModel): text: str; start_ms: int; end_ms: int; speaker: str | None
class SttRun(BaseModel): provider: str; model: str; location: str | None; language_requested: str; language_detected: str | None; adapter_version: str
class SttAdapter(Protocol):
    async def start(self, audio: AudioRef, params: SttParams) -> str   # handle: opaque, JSON-serialisable
    async def poll(self, handle: str) -> Transcript | None             # None = still running
async def transcribe(adapter, audio, params) -> Transcript             # helper: start, then poll until done
```
- **Provider-neutral contract.** Callers know only `start`/`poll` (or the `transcribe()` helper over both). A synchronous provider does its work in `start` and its first `poll` returns the transcript. The Google adapter's batch/long-running semantics stay inside the adapter behind `start/poll`. SP04 stores the handle (`stt_operation`) and resumes it on retry; core never re-submits a handle it was given.
- **Adapters return words only.** The only provider-specific output is a list of `Word{text, start_ms, end_ms, speaker}` plus an `SttRun`. Core `stt/base.py::words_to_turns(words, max_gap_ms)` builds turns (new turn on speaker change or a gap above `max_gap_ms`) and normalises speaker labels to `S1..Sn` by first appearance; `poll` in the shared base class applies it, so no adapter builds turns. An adapter never invents speakers or timestamps (mission rule).
- **Audio.** STT always receives the canonical file SP04's `validate` step writes (FLAC 16 kHz mono, `{uid}/{sid}/audio/canonical.flac`). The adapter decides whether to pass `AudioRef.uri` or read bytes through `local_path_fn`.
- **Adapters.** `GoogleChirp3` (Speech-to-Text v2; `options`: `recognition: standard` (not dynamic batch), `location: us` multi-region, `endpoint: us-speech.googleapis.com` (Chirp 3 is offered in multi-regions us/eu, not us-central1, SP06 R3); long audio via `BatchRecognize` with the default processing strategy, since sync `Recognize` is capped at about 1 min (confirmed by the gate, R11); diarization min/max speakers from params; ADC auth, no keys in code). `FixtureStt` (replays recorded word lists by audio-uri hash; used by tests, api stub, CI).
- **Selection lives in one file**, `config/{env}/stt_providers.yaml` (found next to the routes file, i.e. the directory of `ROUTES_FILE`; a packaged `stt_providers.default.yaml` is used otherwise): `providers: {<key>: {provider, model, options}}`, `default: <key>`, `by_language: {<lang>: <key>}`. `stt/select.py::select_stt(preset_stt_key, language) -> SttParams` applies the precedence preset `stt` → `by_language[lang]` → `default`; the session's `language` overrides any language on the entry. There are no STT env vars. A new provider (e.g. Whisper + diarizer) is one adapter file plus one entry here; callers do not change.

**R5 Transcript types.** `Turn{id, speaker:str|None, text, start_ms:int|None, end_ms:int|None, role:str|None, language:str|None}`, `Transcript{turns, language, duration_ms, stt_run: SttRun}` (typed, R4), `Span{turn_id, start, end}` (code-point offsets, ADR 0002). `eaudit.models.audit.Turn` (API contract, `timestamp: str`, extra=forbid) is NOT replaced; core ships `Transcript.from_eaudit_turns()/to_eaudit_turns()` helpers (ms ↔ `"mm:ss"` string) so api can feed STT output to eaudit.

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

**R10 Run record (r7).** `RunInfo{engine, code_version (env `GIT_SHA`), preset, routes{name: {litellm_id, provider, structured_output_mode, temperature_effective, params_hash}}, stt: SttRun | None, pack{id, version, hash} | None, prompt_hashes, n_runs, usage}`. `provider` is derived from the `litellm_id` prefix; `temperature_effective` is `null` when the route omits temperature; `params_hash` hashes the resolved route entry (never the key). `prompt_hashes` covers pack prompts AND engine-owned prompt templates (the engine passes both file lists to `hash_files()`). No text in `RunInfo`.

**R11 Live checks and gate (r7; none depends on `eval/`).**
- `python -m onolys_core.stt.check --audio <ref> --preset default`: transcribes a 2-speaker sample of at least 10 min through the selected adapter; passes when it finds ≥2 speakers and `start_ms/end_ms` are present and monotonic; prints wall time.
- `python -m onolys_core.llm.smoke --preset default`: one real `complete_json` per default route (and its task aliases); passes when each returns schema-valid JSON; prints model id, latency, tokens. This is what proves the shipped route config.
- **Gate.** Both run before SP02 starts; the result is recorded in ADR 0017 with this decision table:

| Question | If the answer is no |
|---|---|
| (a) Are word time offsets present? | Use another STT model/provider through the adapter (one adapter + one `stt_providers.yaml` entry) |
| (b) Does diarization work with `language: auto`? | Default language becomes `en-US` and `auto` is removed from the web language list (SP05; v1 list is `en-US`, `en-GB`, `auto`) |
| (c) p95 latency for 25 min of audio | Recorded; it must fit SP04's transcribe poll window (about 20 min), otherwise another model/provider as in (a) |

## Architecture
```
api/ ─┐                       protocols/<pack>
paudit ┼─> onolys_core <──────┤ (data, read by engines)
eaudit ┘   llm(routes) · stt · transcript · engine · run_info · safe_log · retry
eval/  ── HTTP only ──> api / eaudit   (no imports)
```
Data flow for the platform: `AudioRef → SttAdapter.start/poll → words_to_turns → Transcript → Engine.run(transcript, pack, params, ctx) → EngineResult`. LLM calls always via `ctx.llm.complete_json(LLMRequest(tier=<route>))`; deterministic code validates (ADR 0005).

## Decisions
| # | Decision | Choice | Alternatives | Why |
|---|---|---|---|---|
| D1 | Packaging | uv workspace (root lock) | Path deps with per-package locks | One lock for api image + engines; consistent versions; CI invokes `--package`. Cost: lock moves to root, `exclude=["eval"]` needed |
| D2 | Package/dist names | dist `onolys-core`, import `onolys_core` | `core` (collides generically) | Unambiguous on `sys.path` |
| D3 | PR split | One PR (move + extract) | PR-A move only, PR-B extract | Faster to a running platform; owner accepted the cut. r7 audit (2026-11-20) |
| D4 | Shims | None; rewrite ~58 imports in the same PR | Keep `eaudit.llm/safe_log/utils` re-exports | Mechanical edit; no second cleanup pass. r7 audit (2026-11-20) |
| D5 | Env prefix | Keep `IAUDIT_*` for engine/eval settings; prefix is one constant in core. Platform deploy config (api, infra: `ENV`, `ROUTES_FILE`, `DEFAULT_PRESET`, …) is unprefixed per SP04/SP06 | `ONOLYS_*` + fallback | `eval`, `vite.config.ts`, docs, scripts use it; rename is cosmetic and costs a back-compat layer; revisit later [DEFERRED] |
| D6 | Route file format | YAML + env overrides for the 3 tiers | Env vars only; JSON | Per-route quirks (`extra_params`) need structure; env keeps today's deploys working |
| D7 | Core `Turn` vs eaudit `Turn` | Separate; convert helpers | Replace eaudit's | Contract 0.0.1 `extra=forbid`; zero behaviour change |
| D8 | eval ↔ engines | Stay decoupled (HTTP) | eval imports core | Existing boundary test; no change to eval deps |
| D9 | STT interface | Provider-neutral `start`/`poll`; adapters return words only; core builds turns; Google-only fields under `options` | Single `transcribe(audio_uri)` with Google fields on `SttParams` | A second provider is one adapter, not a rewrite; long jobs survive worker retries. r7 audit (2026-11-20) |
| D10 | STT selection | One file `stt_providers.yaml`; presets reference an entry by key; no STT env vars | A provider map inside core + STT params repeated in presets + STT env vars | One source of truth. r7 audit (2026-11-20) |
| D11 | Route fields | Limits, timeouts, retries, concurrency, key env and temperature support on the route; task-named routes alias `mid` | Token limits and timeouts in engine settings; tier params per engine | Engines never branch on provider or hold model facts. r7 audit (2026-11-20) |
| D12 | Structured output modes | `json_object`, `json_schema` only | Keep a forced-tool mode | Forced `tool_choice` is rejected by `claude-sonnet-5-5` [verified: claude-api skill]. r7 audit (2026-11-20) |
| D13 | Rate limits | `LLMRateLimited` backs off inside the deadline; semaphore per route | Treat 429 like any error (counts against retries) | Parallel batches hit limits first; failing a run on a 429 wastes it. r7 audit (2026-11-20) |
| D14 | Cache with parallel calls | Warm with one call, then fan out | Fire all calls at once and assume cache hits | A cache entry being written cannot be read. r7 audit (2026-11-20) |
| D15 | Proof of config | Live STT check + LLM smoke as a gate before SP02, result in ADR 0017 | Trust the docs; find out in SP04 | Sample route values are only partly verifiable offline. r7 audit (2026-11-20) |
| D16 | Scope cuts | Routes-file alias env, PHI mode switch, byte-for-byte `/v1/audit` guarantee moved to After launch | Keep as v1 requirements | Owner accepted the cuts. r7 audit (2026-11-20) |

## Manual steps
- Branch protection: none today [verified: `gh api …/branches/main/protection` → 404 "Branch not protected"]. If Tejit adds required checks, job names `eaudit` and `frontend` must be kept (this PRD keeps them).
- Tejit: confirm Speech-to-Text v2 API enabled on project `onolys` and Chirp 3 usable in the `us` multi-region (SP06 R3); ADC quota project must be `onolys` (brief: currently `juno-medical-clarity`).
- Tejit adds the Anthropic API key (`ANTHROPIC_API_KEY`) to Secret Manager (SP06 R10); every default LLM route names it in `api_key_env`.
- Tejit supplies a 2-speaker audio sample of at least 10 min for the STT check (R11).
- Implementer runs the gate (R11) with live credentials and records the result in ADR 0017 before SP02 starts.

## Risks / Open Questions
- [RESOLVED: standard (non-dynamic-batch) recognition; cost not a concern (Tejit 2026-11-20 r6)] The dynamic-batch pricing / `chirp_3` diarization question is moot.
- [RESOLVED: STT location `us` multi-region (reconcile pass); data-residency claims dropped (Tejit 2026-11-20 r6)] Chirp 3 is only documented for `us`/`eu` multi-regions (SP06 R3); no residency claim is made; recorded in ADR 0017 and SP06's ADR.
- [RESOLVED: eval may break; fix if cheap, otherwise disable/skip the eval CI job; not a hack priority (Tejit 2026-11-20 r6)] `uv` behaviour for an excluded standalone `eval/` under a workspace root; verify with `uv sync --project eval` before merging (fallback: D1 alternative, path deps). Also confirm uv tolerates member paths that do not exist yet (`api`, `admin/*`); else add each member as its SP lands.
- [RESOLVED: default LLM is Claude Sonnet via the Anthropic API with `json_object`; `json_schema` for Gemini on Vertex is an optional future route, not evaluated in v1 (Tejit 2026-11-20 r6)] SP01 still ships the `json_schema` switch.
- [OPEN until the gate runs] The sample route's `json_object` mode through LiteLLM and Chirp 3 word offsets / diarization with `language: auto` are unproven; the gate (R11) settles both and its decision table says what changes.
- [RESOLVED: no change needed] frontend dev proxy and `vite.config.ts` have no `eaudit/` paths.
- [RESOLVED: keep] fixture keys use `tier|call_tag|…`; route names equal old tier names so recordings stay valid.
- [DEFERRED] `ONOLYS_*` rename; Whisper adapter; `caudit`; re-running STT on an existing session.
- [DEFERRED: After launch, cut from v1 (r7 audit 2026-11-20)] The two-PR split with re-export shims; the `IAUDIT_LLM_ROUTES_FILE` alias for `ROUTES_FILE`; `IAUDIT_PHI_MODE` and a per-route `phi_allowed` flag; the guarantee that `POST /v1/audit` responses match the old ones byte for byte (existing `/v1/audit` tests must still pass, but responses may show new model ids).

## Acceptance Criteria
1. `eaudit/` no longer exists; `engines/eaudit/` holds it; `git log --follow` works; `grep -rIn "[^s/]eaudit/src" . --exclude-dir=agent_files` finds no stale path.
2. `cd engines/eaudit && uv run pytest -q` passes the same test count as on `main` (only import paths edited); the existing `/v1/audit` tests pass and fixture-replay tests need no re-recording (responses may show new model ids); `cd frontend && npm test` passes; CI jobs `eaudit`, `frontend` green; `cd eval && uv run pytest -q` and the nightly `eval-oracle` dry-run are best-effort (eval is not a v1 priority; a blocking eval job may be disabled/skipped).
3. No `eaudit.llm`, `eaudit.safe_log`, `eaudit.utils.retry` or `eaudit.assembler.locate` module remains (grep); eaudit imports them from `onolys_core`.
4. `onolys_core` imports with no eaudit/paudit/api import (boundary test); `uv run --package onolys-core pytest` covers routes, STT fixture adapter, safe_log, retry.
5. Routes (offline, fake `acompletion`): a route file with a Gemini route (`vertex_ai/gemini-…`, `json_schema`, `caching_mode: none`, empty `extra_params`) is accepted and `LiteLLMClient` builds kwargs from it with no code change; `temperature` is absent when `supports_temperature: false`; `cache_prefixes` + system arrive as one string for `none|provider_implicit` and as annotated blocks for `anthropic_ephemeral`; `max_tokens`/`timeout` come from the route and a larger request value is clamped; a `{alias: mid}` task route resolves to `mid`; a `presets:` entry + `DEFAULT_PRESET` select routes and `ROUTES_FILE` redirects the loader; every default route resolves to the id in the shipped routes YAML; startup fails with an error naming the variable when a route's `api_key_env` is unset.
6. STT (offline): `FixtureStt` returns a `Transcript` with ≥2 speaker labels and `start_ms/end_ms`; `words_to_turns` splits on speaker change and on a gap above `max_gap_ms` and labels speakers `S1..Sn` by first appearance; `poll` on a stored handle resumes without a second submit; `select_stt` follows preset `stt` → `by_language[lang]` → `default` and the session language wins; `GoogleChirp3` request builder unit-tested (diarization min/max from params, language `auto` handled, `options.location: us` → endpoint `us-speech.googleapis.com`); no code reads `STT_*` env vars (grep).
7. A log-capture test shows no transcript/audio text or URI in any core log line.
8. `docs/mission.md` and `AGENTS.md` state the widened scope, keep the 17 checks; `docs/decisions/0017-*` exists; no broken relative links (`grep` link check).
9. Rate limits and caching (offline): a 429 or 529 raises/handles as `LLMRateLimited`, waits at least `retry-after`, retries beyond `max_retries` while the deadline allows and stops at the deadline; concurrent calls on one route never exceed its `max_concurrency` while another route is unaffected; a response cut off at the token limit raises `LLMBadOutput`; `warm_then_fanout` starts no second call before the first has returned.
10. Live LLM smoke: `python -m onolys_core.llm.smoke --preset default` makes one real `complete_json` per default route and exits 0 with schema-valid JSON from each. This run, not the sample YAML, is the proof that the route config is valid.
11. Live STT check: `python -m onolys_core.stt.check --audio <ref> --preset default` on a 2-speaker sample of at least 10 min exits 0 with ≥2 speakers and monotonic `start_ms/end_ms`, and prints wall time.
12. Gate: AC10 and AC11 have run before SP02 starts and ADR 0017 records the result and the answers to the R11 decision table (a)–(c).
13. `RunInfo` (R10) validates for an eaudit run: `code_version` from `GIT_SHA`, `preset`, per-route `{litellm_id, provider, structured_output_mode, temperature_effective, params_hash}`, typed `stt`, `prompt_hashes`; no text and no key value in it.
