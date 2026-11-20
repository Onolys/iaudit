---
status: draft
summary: 13 tasks for SP01 — workspace + interface types first (unblocks SP04), eaudit move, onolys_core extraction, route registry, provider-neutral STT, RunInfo/engine wrapper, live checks, docs, and the gate before SP02.
date: 2026-11-20
---
# Tasks: SP01 core — `engines/` move and shared `onolys_core`
Source of truth: [PRD.md](PRD.md). One PR (D3), no shims (D4). Tests follow SP00 conventions: pytest markers `unit` / `integration` / `live`, default `-m "not live"`; live checks never run in PR CI. CI jobs: `core` (SP00 per-package job, skipped until the package exists) and `eaudit` (name kept for branch protection).

| # | Task | Depends on | Status |
|---|---|---|---|
| 1 | Workspace + core skeleton and shared interface types | none | done |
| 2 | Move `eaudit/` to `engines/eaudit/` and fix paths | 1 | done |
| 3 | Extract llm, safe_log, retry, locate, errors into core; rewrite imports | 2 | done |
| 4 | Route registry, presets and loader | 3 | done |
| 5 | LLM client behaviour driven by routes (limits, caching, rate limits) | 4 | done |
| 6 | `warm_then_fanout` helper | 3 | done |
| 7 | STT core: interface, `words_to_turns`, selection, fixture adapter | 1 | done |
| 8 | Google Chirp 3 adapter | 7 | done |
| 9 | PHI-safe logging generalised | 3 | done |
| 10 | `RunInfo`, transcript converters, `EauditEngine` wrapper | 3, 4, 7 | done |
| 11 | Live checks: `llm.smoke` and `stt.check` | 5, 8 | done |
| 12 | Docs, mission widening, ADR 0017 skeleton, CI finish | 2 | in-progress |
| 13 | Run the gate and record the result in ADR 0017 | 11, 12 | todo |

Parallel lanes: Task 1 is small and goes first. After Task 3, the LLM chain (4, 5, 6), the STT chain (7, 8; only needs Task 1) and Tasks 9 and 12 can run at the same time. Task 10 waits for 4 and 7. Cross-lane sync points: Task 1 (workspace + types; SP04 in Lane B starts on it, push it as soon as it is green) and Task 13 (gate; SP02 may not start before it). Task 2 also fixes the eaudit CI path SP00 left pointing at `eaudit/`.

## Task 1 — Workspace + core skeleton and shared interface types
What it is / what it means: the smallest slice that lets SP04 import stable types. Traces to R8, R4 (types only), R5, R6, D1, D2.
What changes at a high level: root virtual `pyproject.toml` with the uv workspace (`engines/*`, `api`, `admin/*`, exclude `eval`), one root `uv.lock`, and package `engines/core` (`onolys-core` / `onolys_core`) containing only types: `Turn`, `Transcript`, `Span`, `SttParams`, `AudioRef`, `Word`, `SttRun`, `SttAdapter` protocol, `Engine`, `EngineResult`, `RunContext`, `PackRef`, `OnolysError`/`InputError`/`PackError`. Optional extra `stt-google`. Markers registered.
Done when: unit tests validate each model and prove core imports no `eaudit`/`paudit`/`api` (boundary test); `uv sync` works with non-existent members (`api`, `admin/*`), else add members as they land; `uv sync --project eval` still works. The CI `core` job runs the tests green.

## Task 2 — Move `eaudit/` to `engines/eaudit/` and fix paths
What it is / what it means: the pure relocation, history kept. Traces to R1, AC1, AC2.
What changes at a high level: `git mv eaudit engines/eaudit`; `engines/eaudit` becomes a workspace member; fix the `contract.py` repo-root depth, `eval/tests/**` path strings, `eaudit/eval` scripts and READMEs, `scripts/dev.sh` and its README, and `ci.yml`/`nightly.yml` working-directory and cache glob (`uv.lock`, `uv sync --frozen --package eaudit` from root). Link/path text in `README.md`, `docs/**`, `eval/README.md`. Historical `docs/agent_files/**` untouched.
Done when: same eaudit test count as on `main` passes via CI job `eaudit`; `frontend` job green; the stale-path grep (AC1) is clean; `git log --follow` works; eval tests and nightly dry-run are best-effort, and a blocking eval job is disabled or skipped if not cheap to fix (R8 resolution).

## Task 3 — Extract llm, safe_log, retry, locate, errors into core; rewrite imports
What it is / what it means: shared code moves out of eaudit so paudit, evaluation and api reuse it. Traces to R2, D4, AC3.
What changes at a high level: move the LLM types/errors/client/fixture clients, `safe_log`, `retry`, `locate`, and the generic `hash_files()` half of run_info into `onolys_core`; rewrite all imports in eaudit (about 58 files) mechanically; no re-export shims. `eaudit.config.Settings` stays and builds the core `LLMConfig`. Move the matching unit tests to core.
Done when: grep shows no `eaudit.llm`, `eaudit.safe_log`, `eaudit.utils.retry`, `eaudit.assembler.locate` modules or imports; moved tests pass in job `core`; the full eaudit suite passes unchanged in job `eaudit` (fixture keys `tier|call_tag|…` still replay).

## Task 4 — Route registry, presets and loader
What it is / what it means: model choice becomes data, not code. Traces to R3 (registry, presets), D6, D11, D12, AC5.
What changes at a high level: `llm/routes.py` and packaged `routes.default.yaml` with `cheap|mid|strong` and task routes `paudit_code`, `paudit_globals`, `tips` (`alias: mid`), all `anthropic/claude-sonnet-5-5`, `json_object`, `anthropic_ephemeral`, no `thinking`, `supports_temperature: false`. `ROUTES_FILE` override, `presets:` map, `DEFAULT_PRESET`, `resolve_preset()` (unknown name raises `InputError`), startup error naming the variable when `api_key_env` is unset, back-compat env overrides (`IAUDIT_MODEL_*`, `IAUDIT_LLM_RESPONSE_FORMAT`).
Done when: unit tests cover alias resolution, preset selection, `ROUTES_FILE` redirect, the Gemini route (`json_schema`, `caching_mode: none`) accepted, key-unset failure and env overrides; run in job `core`.

## Task 5 — LLM client behaviour driven by routes
What it is / what it means: the client reads limits and quirks from the route; engines never branch on provider. Traces to R3 client behaviour, D13, AC5, AC9.
What changes at a high level: `LLMRequest.tier` becomes a route name; `max_tokens`/`timeout_s` optional and clamped to the route; `temperature` omitted when unsupported; cache prefixes joined or sent as annotated blocks by `caching_mode`; truncation raises `LLMBadOutput`; new `LLMRateLimited` (429/529) backs off with jitter, honours `retry-after`, retries within the deadline without using `max_retries`; one semaphore per route.
Done when: offline tests with a fake `acompletion` prove every AC5 and AC9 behaviour (kwargs, clamp, temperature, caching shape, rate-limit wait and deadline stop, per-route concurrency isolation, truncation); job `core` green and job `eaudit` still green.

## Task 6 — `warm_then_fanout` helper
What it is / what it means: prompt caching needs the first call finished before parallel calls. Traces to R3 (caching), D14.
What changes at a high level: `llm/warm.py::warm_then_fanout(first, rest)` generalising the existing eaudit warmup pattern; eaudit's warmup uses the core helper.
Done when: a unit test shows no second call starts before the first returns and results keep order; job `core` and `eaudit` green.

## Task 7 — STT core: interface, `words_to_turns`, selection, fixture adapter
What it is / what it means: the provider-neutral speech interface and everything that is not Google. Traces to R4, D9, D10, AC6.
What changes at a high level: `stt/base.py` (`start`/`poll` base class, `transcribe()` helper, `words_to_turns` with speaker normalisation to `S1..Sn`), `stt/select.py` with `select_stt` precedence (preset key, `by_language`, `default`; session language wins), packaged `stt_providers.default.yaml` found next to `ROUTES_FILE`, `FixtureStt` replaying word lists by audio-uri hash. No STT env vars.
Done when: unit tests cover the AC6 offline items (two or more speakers with ms times, turn split on speaker change and gap, handle resume without second submit, selection precedence); grep shows no `STT_*` env reads; job `core` green.

## Task 8 — Google Chirp 3 adapter
What it is / what it means: the one real STT adapter, behind `start`/`poll`. Traces to R4 adapters, D9.
What changes at a high level: `stt/google_chirp.py` (Speech-to-Text v2, `BatchRecognize`, standard recognition, `us` multi-region and `us-speech.googleapis.com`, diarization min/max from params, `language: auto` handled, ADC, words only), lazily importing the `stt-google` extra; default entry in `stt_providers.default.yaml`.
Done when: unit tests on the request builder (diarization bounds, auto language, location to endpoint) with the Google client mocked; the core import works without the extra; job `core` green. Real behaviour is proven only by Task 13.

## Task 9 — PHI-safe logging generalised
What it is / what it means: one allowlist logger for all engines. Traces to R7, AC7.
What changes at a high level: base allowlist made generic, `register_fields()` for engines, new fields (`audio_ms`, `stt_provider`, `stt_model`, `language`, `speakers`, `job_id`, `step`), blocked name parts and 200-char cap kept, logger name `iaudit`; eaudit registers today's fields.
Done when: unit tests drop every blocked pattern, and a log capture of a full fixture STT call contains no text or audio URI; eaudit log output is identical (its existing tests pass); jobs `core` and `eaudit` green.

## Task 10 — `RunInfo`, transcript converters, `EauditEngine` wrapper
What it is / what it means: the run record and the engine seam SP02/03/04 build on. Traces to R5, R6, R10, AC13.
What changes at a high level: `RunInfo` model (code_version from `GIT_SHA`, preset, per-route facts with `params_hash`, typed `stt`, pack, prompt hashes covering pack and engine templates, usage; no text, no key); `Transcript.from_eaudit_turns()/to_eaudit_turns()` (ms and `mm:ss`); thin `EauditEngine` in `engines/eaudit` whose `params` pass an optional `profile` through unchanged. `POST /v1/audit` untouched.
Done when: tests validate `RunInfo` for an eaudit run (no text or key value present), converter round-trips, wrapper result equals the direct pipeline result with and without `profile`; jobs `core` and `eaudit` green.

## Task 11 — Live checks: `llm.smoke` and `stt.check`
What it is / what it means: the commands that prove the shipped config against real providers. Traces to R11, AC10, AC11, D15.
What changes at a high level: `python -m onolys_core.llm.smoke --preset default` (one real `complete_json` per default route and alias; prints model id, latency, tokens) and `python -m onolys_core.stt.check --audio <ref> --preset default` (2-speaker sample of at least 10 min; needs two or more speakers and monotonic `start_ms/end_ms`; prints wall time). Neither depends on `eval/`.
Done when: both modules have offline unit tests of their pass/fail logic against fixture clients (CI job `core`), and `live`-marked tests wrap them, skipped in PR CI. Real runs happen in Task 13.

## Task 12 — Docs, mission widening, ADR 0017 skeleton, CI finish
What it is / what it means: docs match the new scope and layout. Traces to R9, AC8.
What changes at a high level: `docs/mission.md` gains "Platform scope" and scoped boundaries (17-check list and the eaudit stance verbatim); `AGENTS.md` line 3 rewritten and docs table gains `engines/`; ADR `0017-*` (workspace, routes, shared core) with an empty gate-result section; `docs/implementation/llm-client.md` repathed plus a routes section; confirm `ci.yml`/`nightly.yml` use the new paths and the `core` job has the `stt-google` extra only if needed.
Done when: a relative-link grep finds no broken links; mission and `AGENTS.md` greps show the widened wording and 17 checks; CI jobs `core`, `eaudit`, `frontend` green.

## Task 13 — Run the gate and record the result in ADR 0017
What it is / what it means: build-time measurements, not design questions. Traces to R11, AC12, D15, the "[OPEN until the gate runs]" item.
What changes at a high level: with live credentials, run `llm.smoke` and `stt.check`. Measure and record in ADR 0017: (1) `json_object` through LiteLLM on each default route; if it fails, move the route to `json_schema` in YAML and re-run. (2) Decision table (a) word offsets present, else another adapter plus entry; (b) diarization with `language: auto`, else default `en-US` and drop `auto` from the SP05 list; (c) p95 for 25 min audio against the SP04 poll window of about 20 min, else another model or provider.
Done when: AC10 and AC11 exit 0 and ADR 0017 records both outputs and the answers to (a)-(c) with any fallback applied; only then is SP02 unblocked. Not run in PR CI (live marker).

## Owner steps (not agent work)
- Confirm Speech-to-Text v2 enabled on project `onolys` and Chirp 3 usable in the `us` multi-region; ADC quota project must be `onolys`.
- Add `ANTHROPIC_API_KEY` (Secret Manager, SP06 R10; env var locally for the gate).
- Supply a 2-speaker audio sample of at least 10 min for the STT check.
- Branch protection: none today; if required checks are added, keep job names `eaudit` and `frontend`.
