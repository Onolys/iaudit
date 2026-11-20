---
status: draft
summary: 12 tasks for SP09 — code-only first (error map, real Stt and Evaluation adapters, artifacts/run_info, offline real-mode flow, live local test, staging presets), then staging-only proof (real audio via web and API key, forced failures + alert, handed-over checks), then recorded results.
date: 2026-11-20
---
# Tasks: SP09 integration — real adapters + staging end-to-end
Source of truth: [PRD.md](PRD.md). Lane B, Slice 1. Tests follow SP00 conventions: markers `unit` / `integration` / `live`, default `-m "not live"`. CI job `api` (SP00 Task 4: ruff + pytest `-m "not live"` under the Firestore emulator + OpenAPI diff) runs everything marked unit/integration here, on fakes and recorded fixtures only. The `live` marker (real LLM/STT calls) runs nightly or manually, never in PR CI. No new endpoints, states, config names or public codes (D2); no provider or model name in SP09 code (D5).

Code-only vs staging-only: Tasks 1-7 need no GCP and no network in CI. They can start once SP03's `run_evaluation` signature and SP04's adapter Protocols (SP04 Task 6) exist; before SP03 lands, a stubbed engine with the same signature is enough. Tasks 8-11 need the SP06 staging env, real audio and the Anthropic key; Task 12 closes the record.

| # | Task | Depends on | Status |
|---|---|---|---|
| 1 | Error map `to_public` + table-driven tests | SP01 T3, SP02 T1, SP04 T5, SP04 T14 | done |
| 2 | Real `Stt` adapter + provider registry | SP01 T7, SP01 T8, SP04 T6, SP04 T8 | done |
| 3 | Real `Evaluation` adapter | SP03 T9, SP02 T6, SP01 T4, SP04 T6 | done |
| 4 | Run artifacts + `run_info` persistence | 3, SP04 T12 | done |
| 5 | Wire `ADAPTERS=real` + error mapping into the worker; offline real-mode flow test | 1, 2, 3, 4, SP04 T12 | done |
| 6 | Local real mode `live` test (fixture STT, real LLM) | 5, SP01 T11 | done |
| 7 | Staging-only presets `test-broken-llm`, `test-broken-eaudit` | SP01 T4 | done |
| 8 | Staging deploy on real adapters; four live checks; web end-to-end + timing | 5, 7, SP05 T14, SP06 T9, SP06 T10 | in-progress |
| 9 | Staging API-key flow + no-rating run | 8, SP04 T15 | todo |
| 10 | Forced failures by preset + failure alert | 7, 8, SP06 T10 | todo |
| 11 | Handed-over checks: Hosting, CSP, `validate` memory, phone | 8, SP05 T12 | todo |
| 12 | Results record, "Engine errors" doc, acceptance sweep | 1-11 | todo |

Parallel lanes: three people can split after the shared seam exists. (a) Task 1 (error map) then 5 (wiring, needs 1-4); (b) Task 2 (Stt) then 6; (c) Task 3 then 4 (Evaluation + artifacts), which both touch the run path, so one person. Task 7 is tiny and independent; give it to whoever finishes first. Tasks 8-11 are sequential on one staging env except 11 (phone/Hosting/CSP) can run beside 10 by a second person once 8 is green. The `preview-real` label from SP00 T7 stays SP00's workflow; it only becomes usable because Task 5 makes `ADAPTERS=real` work. SP09 adds no preview scope. Cross-lane sync points: SP03 signature (Task 3), SP04 Protocols (Tasks 2, 3), SP06 staging + alert channel (Tasks 8, 10), SP05 buildable web and Hosting/CSP config (Tasks 8, 11); SP06 Task 15 consumes Task 12's measurements.

## Task 1 — Error map `to_public` + table-driven tests
What it is / what it means: one place that turns any engine exception into one public code. Traces to R3, D2, D3, AC2.
What changes at a high level: `adapters/error_map.py` with `to_public(exc) -> (code, retryable)` implementing the R3 table (InputError to `invalid_parameters`; PackError and unknown to `internal_error`; LLM errors and `LLMBadOutput` to `upstream_unavailable` retryable; deadline to `deadline_exceeded`; STT transient first attempt `upstream_unavailable` then `transcription_failed`; permanent or poll-limit `transcription_failed`; the `no_speech` / `speakers_not_separated` outcomes). Messages are fixed text, never the exception message. Hooks into SP04's handler wrapper so every mapped failure writes the one `status=failed` line with `exc_class` only.
Done when: a table-driven unit test raises every engine error class from a stubbed engine and asserts code, retry decision, attempt-dependent STT case, one `status=failed` log line with `exc_class` and `request_id`, and no exception message in the API body; CI job `api`.

## Task 2 — Real `Stt` adapter + provider registry
What it is / what it means: SP04's `Stt` Protocol over the SP01 core adapters, provider chosen by data. Traces to R1, D5, AC1.
What changes at a high level: `adapters/real.py` gains the `Stt` implementation: a small registry keyed by the session's stored `stt.provider` (`google_chirp`, `fixture`), `SttParams` from the stored `select_stt` output, `AudioRef` pointing at `audio/canonical.flac` (mime `audio/flac`, duration). `start` returns the handle for `stt_operation`; `poll` returns the core `Transcript` with `stt_run` unchanged. No `if provider ==` in worker code.
Done when: unit tests with `FixtureStt` prove registry lookup, unknown-provider error mapping, `AudioRef` content, transcript passthrough, and that `start` is called once across a retry and a redelivery; a test shows a new provider needs only a registry line; CI job `api`.

## Task 3 — Real `Evaluation` adapter
What it is / what it means: the single call into the evaluation engine. Traces to R2, D5, AC1.
What changes at a high level: `Evaluation` implementation in `adapters/real.py`: builds the core `RunContext` (LLM client from `resolve_preset(run.preset)`, 8-minute `deadline`, `request_id`), loads pack `miti@4.2.1`, calls `run_evaluation(ctx, pack, transcript, speaker_map, params, rating|None, None, progress_cb)` exactly once with `change_goal`, `coded_span`, `language`, `n_runs`, `preset`, `code_version`, and returns `EvaluationOutput`. Never calls engine parts separately; never names a model.
Done when: unit tests with a fixture LLM client / stubbed `run_evaluation` assert the call is made once with the exact params, `progress_cb` is forwarded, a no-rating run passes `rating=None`, unknown preset yields `InputError`, and a grep test finds no model or provider name in the adapter; CI job `api`.

## Task 4 — Run artifacts + `run_info` persistence
What it is / what it means: every run leaves its evidence where SP04 says. Traces to R4, AC3.
What changes at a high level: after the run, write `{uid}/{sid}/runs/{run_id}/{paudit,eaudit,tips}.json` from `EvaluationOutput.artifacts` (a missing part writes nothing), store the report (GCS pointer over 500 KB, SP04 rule) and copy `report.run_info` to the run doc. `RunInfo` carries `code_version` (`GIT_SHA`), `preset`, `routes`, `stt`, `pack{id, version, hash}`, `prompt_hashes`; report header carries `stt`, `preset`, `code_version`. No transcript or rating text in logs (SP04 Task 14 sentinel still passes).
Done when: integration test (fake blob store, emulator) after a real-adapter run over fixtures finds the three artifact files, run doc `run_info` and report header fields, and a no-rating run has no `eaudit.json`; sentinel log test stays green; CI job `api`.

## Task 5 — Wire `ADAPTERS=real` + error mapping into the worker; offline real-mode flow test
What it is / what it means: switch SP04's stub-only seam to real, with no contract change. Traces to R1-R4, D2, AC1, AC2.
What changes at a high level: `ADAPTERS=real` now returns the real adapters instead of raising; worker handlers route every exception through `to_public`; retry decisions follow SP04 R5 (attempt 2 only when retryable). Run with fixture STT and a fixture LLM client so no network is needed.
Done when: the SP04 end-to-end flow test reaches `report_ready` with `ADAPTERS=real` and fixture STT/LLM; `Stt.start` is called once across a forced retry; a transient LLM failure succeeds on attempt 2 and a permanent one ends `failed` with the mapped code; `ADAPTERS=stub` tests still pass unchanged; CI job `api`.

## Task 6 — Local real mode `live` test (fixture STT, real LLM)
What it is / what it means: prove real evaluation runs with no GCP. Traces to R5.
What changes at a high level: a `live`-marked integration test with `ADAPTERS=real`, a local `stt_providers.yaml` whose default is `provider: fixture`, `ANTHROPIC_API_KEY`, `SERVICE_MODE=combined`, running a fixture transcript to `report_ready`. Excluded from PR CI; documented as the nightly/manual command next to SP01's live checks.
Done when: the test is marked `live` and is skipped by `-m "not live"` (verified by CI job `api` collecting but not running it); run manually once with the key, it reaches `report_ready` with a schema-valid report; the nightly workflow gains the invocation or its manual command is recorded.

## Task 7 — Staging-only presets `test-broken-llm`, `test-broken-eaudit`
What it is / what it means: forced failures by config only, no test hooks in production code. Traces to R6, D4, AC7, AC8.
What changes at a high level: two presets in `config/staging/routes.yaml`: `test-broken-llm` points every route at a non-existent model id; `test-broken-eaudit` breaks `cheap|mid|strong` while `paudit_code`, `paudit_globals`, `tips` are full working routes (not aliases). Reachable only through `POST /runs {preset}`; absent from the prod routes file and from the SP04 allowlist for `POST /sessions` unless SP04 already allows them (no SP04 change).
Done when: unit tests load the staging routes through the SP01 loader and assert both presets resolve with the stated breakage, that no alias in `test-broken-eaudit` reaches the broken routes from paudit/tips, and that the prod routes file contains neither; CI job `api`.

## Task 8 — Staging deploy on real adapters; four live checks; web end-to-end + timing
What it is / what it means: the first real run through the actual stack. Traces to R6, AC4, AC9, [OPEN until measured] time target.
What changes at a high level: staging with `ADAPTERS=real`, key seeded, `staging_alerts=true`. Run the four live checks on the default preset (`onolys_core.stt.check`, `onolys_core.llm.smoke`, `paudit.cli check`, `onolys_evaluation.check`). Then take one real 10-25 min two-speaker recording through the web app: upload, transcript, speaker confirm, card, report. Record upload-complete to `transcript_ready` (compare with the SP01 gate p95) and final-card-submitted to `report_ready`.
Done when: all four checks pass; the web run reaches `report_ready` with run-start-to-report at or under 5 min at N=1, numbers recorded; if missed, tune route config (`max_concurrency`, timeouts) and `worker_max_instances` (not task fan-out), re-measure, and record the figure and lever used. Evidence is the staging run plus the recorded numbers; unit/integration coverage stays in CI job `api` (Tasks 1-5).

## Task 9 — Staging API-key flow + no-rating run
What it is / what it means: the second front door and the optional-card path. Traces to R6, AC5, AC6.
What changes at a high level: with an API key from `/api-key`, run the `/v1/docs` curl quickstart sequence on a real recording through to a report; then a no-rating run (card with change goal only, `no_rating`) that yields Onolys scores and tips with `reasons_audit.status: skipped`.
Done when: both runs reach `report_ready` within the Task 8 target; the no-rating report shows `reasons_audit.status: skipped` and Task 4's no-eaudit artifact rule holds on staging; curl transcript and timings recorded (no transcript or rating text).

## Task 10 — Forced failures by preset + failure alert
What it is / what it means: the real error path and the owner alert, proven end to end. Traces to R3, R6, D3, D4, AC7, AC8, AC10.
What changes at a high level: `POST /runs {preset: "test-broken-llm"}` must end `failed` with `error_code=upstream_unavailable` after both attempts; then "Run again" on the default preset yields a report. `POST /runs {preset: "test-broken-eaudit"}` ends `report_ready` with `reasons_audit.status: failed` and warning `reasons_audit_failed`. Confirm one alert email arrives for the broken-LLM failure and that the SP06 runbook query finds the `status=failed` line by `request_id`.
Done when: all four outcomes observed on staging and recorded; exactly one alert email and one failed log line per failure; if the key's rate tier makes runs slow rather than failing, note it in the results. Offline equivalents of the mapping live in Tasks 1 and 5 (CI job `api`).

## Task 11 — Handed-over checks: Hosting, CSP, `validate` memory, phone
What it is / what it means: staging-only claims earlier sub-projects deferred here. Traces to R6, AC11, [OPEN until measured] `validate` memory.
What changes at a high level: (a) Hosting forwards `Authorization` and does not cache `/v1` (response headers inspected through the Hosting domain); (b) no CSP violation in the browser console during the web flow, Firestore listener and Identity Platform popup hosts exact (SP05 R8); (c) `validate` of a 300 MB upload with a second task running, watching worker memory and restarts; (d) manual phone check: sign-in (Google redirect fallback) and a large upload on iOS Safari.
Done when: each of the four is recorded pass; for (c), peak memory recorded and no out-of-memory restart, else apply the fallback (worker memory to 4 GiB via the tfvar, or concurrency 1) and re-run; any CSP or Hosting finding is fixed in SP05/SP06 files by their owners or logged as a handed-back item. Evidence is recorded numbers and headers, not new CI tests.

## Task 12 — Results record, "Engine errors" doc, acceptance sweep
What it is / what it means: leave measured facts and the error contract written down. Traces to R3, R6, AC1-AC11.
What changes at a high level: `docs/reference/staging-e2e.md` (numbers only: timings, memory, levers used, outcomes, no recording content); the "Engine errors" section of `docs/reference/public-api.md` mirroring the R3 table; a checklist mapping each AC to its passing test or recorded staging result; staging test data (uploaded recordings, sessions) deleted after the run.
Done when: a doc-consistency test checks the public-api section lists exactly the codes in the `to_public` table; all AC1-AC3 tests pass under `uv run --package onolys-api pytest -q -m "not live" api/tests/integration`; AC4-AC11 each point to a recorded result; CI job `api` green; SP06 Task 15 can consume the measurements.

## Owner steps (not agent work)
- Tejit: provide 2-3 real mock-interview recordings (10-25 min, two speakers). Upload through the app only; never commit them; delete from staging afterwards.
- Tejit: Anthropic API key seeded into staging by `seed-secrets.py` (SP06 Task 8); confirm the alert email channel (SP06 Task 10) so the Task 10 email can arrive.
- Tejit (or anyone with an iPhone): the Task 11 phone check.
- Tejit: grant a long enough Anthropic rate tier if runs back off noticeably (recorded as a risk, not a blocker).
