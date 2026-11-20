---
status: draft
summary: Wire the real `Stt` and `Evaluation` adapters into the SP04 worker, map engine errors to public error codes, persist run artifacts and `run_info`, and prove the whole flow on staging with real audio (web and API key), including the checks SP04/05/06 handed over.
date: 2026-11-20
---
# PRD: SP09 integration — real adapters + staging end-to-end

Repo/branch: Onolys/onolys (local `iaudit`) / `feat/miti-platform` · Depends on: SP02 (paudit + pack), SP03 (`run_evaluation`), SP04 (worker, adapter Protocols, storage paths, error schema), SP06 (staging env, secrets, alerts); SP05 for the web check; SP01 through all of them · Owns: `api/src/onolys_api/adapters/real.py` (the two real adapters), `api/src/onolys_api/adapters/error_map.py`, `api/tests/integration/**`, two staging-only test presets in `config/staging/routes.yaml`, the "Engine errors" section of `docs/reference/public-api.md`, `docs/reference/staging-e2e.md` (measured results)
Not owned: engine code (SP01-03), the adapter Protocols, state machine, storage layout and error schema (SP04), web UI (SP05), Terraform and alerts (SP06).

## TL;DR
SP04 ships on fake adapters. This sub-project is "Slice 1": it adds the real `Stt` and `Evaluation` adapters behind `ADAPTERS=real`, turns every engine exception into one public error code, stores run artifacts and `run_info` where SP04 says, and runs the full flow on staging with real 10-25 min recordings. It also closes the staging checks SP04/05/06 pointed here. No new endpoints, states or config names.

## Problem
- SP04's worker only calls fakes; nothing connects it to `onolys_core` STT, `paudit` and `onolys_evaluation`. [verified: SP04 R6, D20]
- Engines raise typed errors (`InputError`, `PackError`, `LLM*`, STT adapter errors); the public API has a closed error enum. Nobody owns the mapping.
- Several claims are only provable on staging: the time target, Hosting pass-through, CSP hosts, worker memory, the failure alert.

## Goals / Non-Goals
**Goals:** real engines run in the worker with no change to SP04's contract; one mapping table from engine error to public code; artifacts and `run_info` complete for every run; the documented time target measured; swapping the LLM or STT stays config-only through the adapters (no provider or model name in SP09 code).
**Non-goals:** engine logic or prompts; new API surface; quality tuning on real data (SP02/SP03 deferred items); prod launch itself (follows this); the admin site (SP07, After launch).

## Requirements
**R1 Real `Stt` adapter.** Implements SP04's `Stt` Protocol over SP01 `SttAdapter.start/poll`. Picks the core adapter class from the session's stored `stt.provider` through a small registry (`google_chirp` → `GoogleChirp3`, `fixture` → `FixtureStt`); builds `SttParams` with SP01 `select_stt` output stored at session creation, and `AudioRef{uri: gs://…/audio/canonical.flac, local_path_fn, mime: audio/flac, duration_ms}`. Returns the handle for `stt_operation`; `poll` returns the core `Transcript` (with `stt_run`) unchanged. A new STT provider = one core adapter + one registry line + one `stt_providers.yaml` entry.

**R2 Real `Evaluation` adapter.** Builds `ctx` (core `RunContext`: LLM client from `resolve_preset(run.preset)`, `deadline` = SP04's 8-min internal deadline, `request_id`), loads the pack (`miti@4.2.1`), and calls SP03 `run_evaluation(ctx, pack, transcript, speaker_map, params{change_goal, coded_span{from_s,to_s}, language, n_runs, preset, code_version}, rating|None, None, progress_cb)` once. Returns SP03's `EvaluationOutput{report, artifacts{paudit, eaudit, tips}}`. It never calls engine parts separately and never names a model.

**R3 Error mapping** (`error_map.py`; one function `to_public(exc) -> (code, retryable)`; codes are from SP04 `public-error-response.schema.json`; message text is fixed, never the exception message):
| Raised by engines | Public `error_code` | Retry (SP04 R5) | User action (SP05) |
|---|---|---|---|
| `InputError` (pack input checks: too long, no change goal, too few clinician/client turns; unknown preset) | `invalid_parameters` | no | Run again after fixing the input (e.g. change who the clinician is) |
| `PackError` | `internal_error` | no | Run again; owner alerted |
| `LLMUnavailable`, `LLMTimeout`, `LLMRateLimited` past the deadline, `LLMBadOutput` after the engine's own retries | `upstream_unavailable` | yes (attempt 2) | Run again |
| Internal deadline passed (`RunContext.deadline`) | `deadline_exceeded` | yes (attempt 2) | Run again |
| STT adapter error, transient (provider 429/5xx) | `upstream_unavailable` on attempt 1, then `transcription_failed` | yes | Upload a different file |
| STT adapter error, permanent; no result within the poll limit | `transcription_failed` | no | Upload a different file |
| Transcript with 0 turns or <50 words / <2 usable speakers (SP04 R4 checks) | `no_speech` / `speakers_not_separated` | no | Upload a different file |
| Anything else | `internal_error` | no | Run again; owner alerted |
An eaudit or tips failure inside `run_evaluation` is not an error here: SP03 returns a report with warning `reasons_audit_failed | reasons_audit_partial | tips_failed` and the session ends `report_ready`. Every mapped failure writes SP04 R10's one `status=failed` log line with `exc_class`.

**R4 Artifacts and `run_info`.** After a run the worker writes, at SP04 R7's paths, `{uid}/{sid}/runs/{run_id}/{paudit,eaudit,tips}.json` from `EvaluationOutput.artifacts` (a missing part, e.g. eaudit on a no-rating run, writes nothing), stores the report (GCS pointer when >500 KB) and copies `report.run_info` onto `runs/{run_id}.run_info`. Each `RunInfo` (SP01 R10) carries `code_version` (= `GIT_SHA`), `preset`, `routes{…}`, `stt`, `pack{id, version, hash}`, `prompt_hashes`; the report header carries `stt`, `preset`, `code_version`. No transcript or rating text in logs.

**R5 Local real mode.** `ADAPTERS=real` with a local `stt_providers.yaml` whose default entry is `provider: fixture`, plus `ANTHROPIC_API_KEY`, runs the real evaluation on a fixture transcript in `SERVICE_MODE=combined` with no GCP. An integration test (marked `live`, not in CI) does exactly that.

**R6 Staging end-to-end** (staging env from SP06, `staging_alerts=true` for the run; results recorded in `docs/reference/staging-e2e.md`, numbers only):
- Real 10-25 min 2-speaker recordings go upload → transcript → speaker confirm → card → report, once through the web app and once with an API key (the `/v1/docs` curl quickstart).
- **Time target:** SP04's target, ≤5 min from run start (final card submitted with transcript and speaker confirm in) to `report_ready` at N=1. Also recorded: upload-complete → `transcript_ready` time (compare with the SP01 gate's p95).
- **Forced failures by config only:** two staging-only presets in `config/staging/routes.yaml`, used through `POST /runs {preset}`: `test-broken-llm` (every route points at a model id that does not exist) and `test-broken-eaudit` (`cheap|mid|strong` broken; `paudit_code`, `paudit_globals`, `tips` are full working routes instead of aliases).
- **Handed-over checks:** Hosting forwards `Authorization` and does not cache `/v1` (SP04/SP05/SP06); the web CSP hosts for the Firestore listener and the Identity Platform popup are exact (SP05 R8); `validate` peak memory with a 300 MB upload stays inside the worker's 2 GiB with a second task running (SP04 risk); a manual phone check of sign-in (Google redirect fallback) and a large upload on iOS Safari (SP05 risk).

## Architecture
```
worker task ─► adapters (ADAPTERS=real)
   Stt        ─► onolys_core.stt  select registry ─► SttAdapter.start/poll ─► Transcript(stt_run)
   Evaluation ─► onolys_evaluation.run_evaluation(ctx, pack, …, progress_cb) ─► EvaluationOutput
                    └─ exceptions ─► error_map.to_public ─► session/run `failed` + error_code (+ one log line ─► SP06 alert)
   EvaluationOutput ─► report (Firestore | GCS) · artifacts (GCS runs/{run_id}/) · run_info (run doc)
```

## Decisions
| # | Decision | Choice | Alternatives considered | Why |
|---|---|---|---|---|
| D1 | Ownership | Own sub-project with its own acceptance | "Thin follow-up" inside SP04 | Integration had no owner; staging proof needs explicit criteria. r7 audit (2026-11-20) |
| D2 | Error mapping | One table, existing public codes only | New public codes per engine error | SP05's error table already covers them (others fall to its generic message); nothing leaks engine detail |
| D3 | `LLMBadOutput` | Retryable (`upstream_unavailable`) | Permanent `internal_error` | A second attempt often succeeds; the engine has already halved/retried inside |
| D4 | Forced failures | Staging-only presets with broken routes | Failure flags in code; magic titles in real mode | Tests the real error path with no test hook in production code |
| D5 | Provider choice in the adapter | Registry keyed by `stt.provider`; LLM client from the preset | `if provider == …` in worker code | Model/provider swap stays config or one small adapter |

## Manual steps
- Tejit: provide 2-3 real mock-interview recordings (10-25 min, two speakers) for the staging run; they are uploaded through the app, never committed, and deleted from staging afterwards.
- Tejit: provide the Anthropic API key (seeded into staging by `seed-secrets.py`, SP06 R10) and confirm the alert email channel (SP06 manual step 9), so the forced-failure email can arrive.
- A person with an iPhone (Tejit by default) does the phone check in R6.

## Risks / Open Questions
- [OPEN until measured] The ≤5-min run-start-to-report target and the transcription time on real 25-min audio; if missed, the levers are route config (`max_concurrency`, timeouts) and `worker_max_instances`, not task fan-out (SP04).
- [OPEN until measured] `validate` peak memory with a 300 MB upload; fallback: worker memory to 4 GiB (a tfvar) or concurrency 1.
- [RESOLVED: SP04's public enum is a superset of the eaudit enum, so `invalid_parameters`, `upstream_unavailable`, `deadline_exceeded`, `internal_error` exist (SP04 R9)] Codes used by the mapping.
- Risk: the Anthropic key's rate tier is too low for 6 parallel runs; the client backs off (SP01 R3), runs get slower rather than fail; recorded in the staging results.
- [DEFERRED] Load test beyond worker capacity; quality comparison against certified-coder ratings (SP02/SP03 deferred items).

## Acceptance Criteria
1. Offline: with `ADAPTERS=real`, fixture STT and a fixture LLM client, the SP04 flow test reaches `report_ready`; the `Stt` adapter passes an `AudioRef` to `canonical.flac` and `start` is called once across a retry.
2. Error mapping: a table-driven test raises each engine error from a stubbed engine and asserts the public code, the retry decision and one `status=failed` log line with `exc_class`; no exception message reaches the API body.
3. Artifacts: after a real-adapter run, `{uid}/{sid}/runs/{run_id}/{paudit,eaudit,tips}.json` exist, the run doc's `run_info` and the report header carry `code_version`, `preset`, routes, `stt`, pack hash and prompt hashes; a no-rating run writes no `eaudit.json`.
4. Staging, web: one real 10-25 min recording goes upload → report, and `report_ready` arrives within 5 min of submitting the final card (transcript and speaker confirm already in); the measured times are recorded.
5. Staging, API key: the same flow with the curl quickstart and an API key produces a report within the same target.
6. Staging: a no-rating run produces a report (Onolys scores + tips, `reasons_audit.status: skipped`).
7. Staging: `POST /runs {preset: "test-broken-llm"}` ends `failed` with `error_code=upstream_unavailable`; "Run again" on the default preset then produces a report.
8. Staging: `POST /runs {preset: "test-broken-eaudit"}` ends `report_ready` with `reasons_audit.status: failed` and warning `reasons_audit_failed`.
9. The four live checks pass on the default preset against staging credentials: `python -m onolys_core.stt.check --audio <ref> --preset default`, `python -m onolys_core.llm.smoke --preset default`, `python -m paudit.cli check --pack miti@4.2.1 --preset default`, `python -m onolys_evaluation.check --preset default`.
10. The forced failure in AC7 sends one alert email to the owner's channel, and the SP06 runbook query finds its log line by `request_id`.
11. Handed-over checks recorded as pass (or their fallback applied): Hosting `/v1` forwards `Authorization` and is not cached; no CSP violation in the browser console during the web flow; `validate` of a 300 MB upload completes with no worker out-of-memory restart; the phone check passes.
