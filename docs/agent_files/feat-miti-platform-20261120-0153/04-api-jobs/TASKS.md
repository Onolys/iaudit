---
status: draft
summary: 16 tasks for SP04 — API skeleton + combined mode + committed openapi.json first, then repo/auth/sessions, queue + worker semantics, upload/transcribe, rating, first-run transaction, run + reports, delete, logging, docs, acceptance. All local on fakes.
date: 2026-11-20
---
# Tasks: SP04 api + jobs — public API, job orchestration, storage
Source of truth: [PRD.md](PRD.md). Lane B (platform). Built and accepted on fake adapters (D20); real engines are SP09. Tests follow SP00 conventions: markers `unit` / `integration` / `live`, default `-m "not live"`; no test needs network or GCP. CI job `api` (SP00 Task 4: ruff + pytest `-m "not live"` under `firebase emulators:exec` with the Firestore emulator + regenerate and diff `api/openapi.json`), skipped until `api/` exists. Every task is runnable fully locally (emulator, `FakeRepo`, `FakeBlobStore`, `AUTH_MODE=fake`, `SERVICE_MODE=combined`); only real Cloud Tasks/IAM signing/Hosting rewrite need SP06 staging, and those checks are SP06/SP09's.

| # | Task | Depends on | Status |
|---|---|---|---|
| 1 | API skeleton, `SERVICE_MODE=combined`, healthz, error schema, committed `openapi.json` | SP01 T1 | done |
| 2 | `Repo` protocol, Firestore + fake repos, blob store, data model, indexes | 1 | done |
| 3 | Auth: ID tokens, API keys, `/api-key` | 1, 2 | done |
| 4 | Sessions: create (idempotent), list, get, `session_status`, state machine core | 2, 3 | done |
| 5 | Task queue + worker framework (retry, idempotency, OIDC) | 1, 2 | done |
| 6 | Engine adapters and fakes (`Stt`, `Evaluation`) | 1 | done |
| 7 | Audio upload, `complete`, `validate` + FLAC transcode | 4, 5, 2 | done |
| 8 | `transcribe` + `transcribe-poll` | 5, 6, 7 | done |
| 9 | Daily cap, concurrent-run limit, `GET /usage` | 2, 4 | done |
| 10 | Rating card: drafts, final revisions | 4 | done |
| 11 | Speakers, transcript read, `maybe_start_first_run` transaction | 8, 9, 10 | done |
| 12 | `run` task, progress, partial failure, reports, `POST /runs` | 6, 9, 11 | done |
| 13 | Delete (hard) + cleanup task | 7, 12 | done |
| 14 | Logging/privacy registration and sentinel test | 12 | done |
| 15 | OpenAPI finalisation, `/v1/docs`, contracts, public-api doc, ADR 0020 | 12, 13 | in-progress |
| 16 | Dockerfile, dev script, end-to-end acceptance sweep | 13, 14, 15 | todo |

Parallel lanes: Task 1 goes first and alone; push it as soon as it is green because SP05 (Lane C) generates its client from `api/openapi.json` and SP00's PR-preview task (SP00 T7) needs `SERVICE_MODE=combined` runnable. It depends only on SP01 Task 1 (workspace + shared types), the sync point with Lane A. After Task 1, three people can split: (a) Task 2 then 3 (storage, auth/keys), (b) Task 5 (queue/worker semantics) then 7 and 8 (upload/transcode, transcribe), (c) Task 6 (adapters/fakes) then 10 (rating card) and 9 (cap, after 2). Task 4 needs 2 and 3 and unlocks 7 and 10; the state-machine and first-run logic (4, 11, 12) are best kept to one person because they share `jobs/machine.py`. Tasks 13, 14 and 15 are independent of each other after 12 and can run concurrently. Cross-lane sync points: Task 1 (to SP05 and SP00), Task 15 (final `openapi.json` to SP05, report schema from SP03 stored verbatim), SP06 (staging env for the first preview and for SP09's deploy checks, not for this sub-project's acceptance), SP09 (takes over the adapter seam in Task 6).

## Task 1 — API skeleton, `SERVICE_MODE=combined`, healthz, error schema, committed `openapi.json`
What it is / what it means: the contract-first slice others code against. Traces to R9, R11, R12, D1, D6, D10, AC10, AC12.
What changes at a high level: workspace member `api/` (`onolys_api`) with app factory, `config.py` reading the env vars from the SP06 interface (including `FIRESTORE_DATABASE`, `ADAPTERS`, `SERVICE_MODE=api|worker|combined`), `/v1/healthz`, `onolys_api.errors` (`ApiError`, `error_body`) and `docs/contracts/public/public-error-response.schema.json` (superset of the eaudit enum, `schema_version "0.0.1"`, new codes), CORS, request id, `python -m onolys_api.openapi`, committed `api/openapi.json`, `api/.env.example`. Combined mode wires an in-memory queue stub (filled in Task 5).
Done when: unit tests cover error bodies validating against the new schema and `request_id` echo, healthz via httpx ASGI, config parsing and the `AUTH_MODE=fake` guard; an integration test starts combined mode; CI job `api` runs green including the OpenAPI regenerate-and-diff check.

## Task 2 — `Repo` protocol, Firestore + fake repos, blob store, data model, indexes
What it is / what it means: the single uid-checked choke point and the storage seams. Traces to R7, R12, D7, D11, AC3.
What changes at a high level: `repo/base.py` protocol requiring `uid` on every call (404 on mismatch, never 403), `FirestoreRepo` (honours `FIRESTORE_DATABASE`), `FakeRepo` recording `session_status` writes, typed documents for every collection in the R7 table, large-object rule (transcript/report over 500 KB to GCS with a pointer), `storage/` with GCS V4 blob store and `FakeBlobStore` (local dir, fake signed URLs served by the app), `api/firestore.indexes.json` with `sessions(uid, created_at desc)`.
Done when: unit tests run the same repo contract suite against `FakeRepo` and the Firestore emulator; a two-user suite proves cross-uid reads return not-found; a test greps the repo layer so no collection query lacks a uid filter; pointer round-trip for a >500 KB object passes. CI job `api`.

## Task 3 — Auth: ID tokens, API keys, `/api-key`
What it is / what it means: two auth paths to one `uid`. Traces to R1, D9, AC4.
What changes at a high level: `current_user` dependency accepting Identity Platform ID tokens (Google public keys, `aud`, `iss`, expiry, `email_verified`) or `X-API-Key: onolys_<id>_<secret>` (SHA-256 of a 256-bit secret, id-prefix lookup, constant-time compare, `last_used_at`); `GET/POST/DELETE /api-key` (one active key, regenerate = revoke+create, secret shown once, token-only); `AUTH_MODE=fake` accepting `Bearer test:<uid>` only in `ENV=local|test`; `users/{uid}` created on first sight. Per-minute rate limiting is not built (After launch).
Done when: unit tests cover invalid/expired/unverified token and revoked key giving 401 `unauthenticated`, regenerate invalidating the old key, stored hash never equal to the secret, API key refused on key management; the fake-auth guard is tested outside local/test; integration test against the emulator; CI job `api`.

## Task 4 — Sessions: create (idempotent), list, get, `session_status`, state machine core
What it is / what it means: the session record and the PHI-free status document the web subscribes to. Traces to R2 (create, list, get), R4, R7, D4, D8, D13, D18, AC11.
What changes at a high level: `POST /sessions` (language, `n_runs`, allowlisted `preset` else 422, `title`, `Idempotency-Key` store with 24 h body-hash replay and 409 `conflict`), STT params resolved once through SP01 `select_stt` (SP01 T7) and stored on the session; one batch writes `sessions/{sid}` and `session_status/{sid}`; `GET /sessions` with `limit`/`cursor`; `GET /sessions/{id}`; `jobs/machine.py` with the state enum, allowed transitions (409 `invalid_state`), the four flags, the R4 progress table and a single status-mirror helper.
Done when: unit tests cover transitions, `progress` never decreasing, status-doc schema (no transcript/rating/report text), existence before the call returns, unknown preset 422, idempotent replay and conflict, pagination; integration test lists in-flight, failed and done sessions; CI job `api`.

## Task 5 — Task queue + worker framework (retry, idempotency, OIDC)
What it is / what it means: how work leaves the API and how handlers behave. Traces to R5, D3, AC6, AC12.
What changes at a high level: `jobs/queue.py` with a Cloud Tasks implementation (task names `{sid}-validate`, `{sid}-transcribe`, `{sid}-poll-{n}`, `{run_id}-run`, delayed polls, request id in payload) and the in-memory queue that calls handlers directly in combined mode; worker route with OIDC audience check (bypassed only in `ENV=local|test`); handler wrapper implementing 2xx-for-permanent, 5xx-only-when-retryable-and-attempt<2 (via `X-CloudTasks-TaskRetryCount`), step record claim with lease (deadline+60 s), internal 8-min deadline, status mirror on every transition. No app-level retry loop.
Done when: unit tests inject a transient failure (succeeds on attempt 2), two failures (ends `failed`, no third attempt), a permanent error (not retried) and duplicate delivery (one result); the worker rejects calls without valid OIDC outside local/test. CI job `api`. Real Cloud Tasks behaviour is only checkable on SP06 staging (SP09).

## Task 6 — Engine adapters and fakes (`Stt`, `Evaluation`)
What it is / what it means: the only seam to the engines; fakes make SP04 acceptable alone. Traces to R6, D2, D20, AC15.
What changes at a high level: `adapters/` with exactly two Protocols (`Stt` wrapping SP01 `SttAdapter.start/poll` (SP01 T7) with `AudioRef`/`SttParams`; `Evaluation` wrapping `run_evaluation` with `progress_cb`), `ADAPTERS=stub|real` switch (real raises until SP09), deterministic sleep-free schema-valid fakes (report validated against SP03 `report.schema.json` (SP03 T1), paudit output against SP02's schema, as far as those exist), `progress_cb` for every stage, failure injection by magic session title (paudit failed; eaudit and tips failed; the three transcribe codes), `FixtureStt` for tests.
Done when: unit tests prove determinism, schema validity of fake outputs, each injection path, and that the fake `Stt` records `start` call counts; CI job `api`.

## Task 7 — Audio upload, `complete`, `validate` + FLAC transcode
What it is / what it means: bytes in safely, one canonical format out. Traces to R2 (audio), R3, D5, AC5 and the validate memory risk.
What changes at a high level: `POST …/audio` (alias mapping to canonical type, `unsupported_audio`/`audio_too_large` 422, signed PUT with `required_headers` into `uploads/{uid}/{sid}/{upload_id}`, state `uploading`), `POST …/audio/complete` (202, enqueues `validate`), `GET …/audio` signed read, the `validate` step (size, magic bytes, `ffprobe` duration 1 s to 25 min, audio stream, `short_recording` warning, move to `{uid}/{sid}/audio/original.{ext}`, ffmpeg to `canonical.flac` 16 kHz mono, delete staged object, failure codes plus object removal) and the recording doc. Measure and record peak memory of validate on a 25-min sample locally; staging figure is SP09's, fallback worker 4 GiB or concurrency 1.
Done when: unit tests (ffprobe stubbed with tiny wav fixtures) cover each rejection code and warning, all four alias cases; one integration test with real ffmpeg proves FLAC/16 kHz/mono and that the fake `Stt` receives an `AudioRef` to it; CI job `api`.

## Task 8 — `transcribe` + `transcribe-poll`
What it is / what it means: transcription without holding a request or paying twice. Traces to R4 (Transcribe), D16, AC6.
What changes at a high level: `transcribe` calls `Stt.start` once, stores `stt_operation` on its step record, enqueues delayed polls (about 15 s, total limit about 20 min); retry/redelivery resumes polling and never re-submits; stored `Transcript` (pointer when >500 KB); outcome checks giving `no_speech`, `speakers_not_separated`, `transcription_failed`; on success `transcript_ready=true`, state `awaiting_input`, then calls the first-run hook (stubbed until Task 11).
Done when: unit tests prove `start` called exactly once across retry and redelivery, polls stop at the time limit with `transcription_failed`, fixtures for 0 turns, under 50 words, one speaker and a 5% speaker fail with the right code, and a 3-speaker fixture reaches the gate; CI job `api`.

## Task 9 — Daily cap, concurrent-run limit, `GET /usage`
What it is / what it means: spend guard checked at run creation. Traces to R8, D14, AC7.
What changes at a high level: transactional per-uid UTC-day counter (`DAILY_RUN_CAP=20`, per-user override on `users/{uid}`), concurrent-active-run limit of 2, refund when a run fails before any LLM call, `GET /usage {runs_today, daily_cap, resets_at}`, 429 `details[].code=daily_cap_reached`; a reusable cap-check used by auto-start and `POST /runs`.
Done when: unit tests on emulator prove the 21st run returns 429, concurrent attempts cannot exceed the cap (transaction test), refund on failure-before-LLM, and the concurrent-run limit behaves the same way; CI job `api`.

## Task 10 — Rating card: drafts and final revisions
What it is / what it means: the in-app rating card with autosave and no parsing. Traces to R2 (rating), R7, D15, AC11, AC14.
What changes at a high level: `PUT/GET /sessions/{id}/rating` with `final` and `no_rating`; draft doc overwritten and size-limit-only checked; final revision `ratings/{rating_id}` validated through SP03 `validate_rating` (SP03 T2) (jsonschema against SP02 `rating.schema.json` (SP02 T2) until SP03 lands), `change_goal` required, "no rating" detection (`has_rating=false`), `rating_invalid` 422 above 1,000 / 3,000 chars; copies `change_goal`/`coded_span` to the session; sets `rating_submitted`/`has_rating` and mirrors status; allowed in every state but `deleting`; calls the first-run hook (stubbed until Task 11). Firestore only.
Done when: unit tests cover draft never changing `rating_submitted` or starting a run, each final creating a new revision, `GET` draft-only-when-newer, limits, rejection only in `deleting`, and no object written under any GCS rating path; `openapi.json` has no upload/parse endpoints; CI job `api`.

## Task 11 — Speakers, transcript read, `maybe_start_first_run` transaction
What it is / what it means: the last human gate and the race-free auto-start. Traces to R2 (speakers, transcript), R4 (first run), D13, AC13, AC18.
What changes at a high level: `GET …/speakers` (3 sample lines per speaker, all speakers listed), `POST …/speakers/confirm` (202; also in `report_ready|failed` where it applies to the next run only), `GET …/transcript` (owner-scoped, `private, no-store`, 409 before ready), and `maybe_start_first_run(sid)` as one Firestore transaction checking the three flags, `first_run_id` absent and the cap, creating the run (snapshot of `rating_id`, `n_runs`, `preset`, `stt`, `code_version` from `GIT_SHA`), setting `state=running`, enqueuing `{run_id}-run` after commit. Cap hit leaves `awaiting_input` with `error_code=daily_cap_reached`. Wire Tasks 8 and 10 to it.
Done when: a race test fires `PUT rating final`, `speakers/confirm` and transcribe completion concurrently in all orders, repeated, and yields exactly one run and one `run` task with `first_run_id` set once; cap-at-auto-start test; confirm-in-`report_ready` leaves the existing report unchanged; CI job `api` (emulator).

## Task 12 — `run` task, progress, partial failure, reports, `POST /runs`
What it is / what it means: the whole evaluation as one task, and the versioned report. Traces to R4 (Run), R5, R6, R7, D2, D12, D17, D18, AC2, AC15, AC16.
What changes at a high level: `run` handler calling the `Evaluation` adapter in-process with `progress_cb` mapped to `session_status.step` and the stage-weight table; partial failure rule (paudit failed fails run and session; eaudit/tips failures still ship with warnings); report stored verbatim (validated against SP03 `report.schema.json` (SP03 T1), `report_schema_version` copied, >500 KB to GCS), run artifacts at `{uid}/{sid}/runs/{run_id}/{paudit,eaudit,tips}.json`, run record fields (`stt`, `preset`, `code_version`, `rating_id`); `POST /sessions/{id}/runs`, `GET …/runs`, `GET /runs/{run_id}`, `GET …/reports`, `GET …/reports/{version}`; re-run reuses the transcript and latest final rating; retried `run` re-runs everything and yields one report; refund path to Task 9.
Done when: integration tests prove the full stub flow to `report_ready`, a second `POST /runs` gives v2 while v1 still resolves, a re-run with another preset does not call `Stt` again, each injected failure gives the specified outcome, a >500 KB report is served unchanged, and `progress` follows the table; CI job `api`.

## Task 13 — Delete (hard) + cleanup task
What it is / what it means: complete deletion with an idempotent retry. Traces to R7 (Delete), AC8; the delete race is [DEFERRED] and not built.
What changes at a high level: `DELETE /sessions/{id}`: mark `deleting` (blocks reads and new runs), list-and-delete all objects under `{uid}/{sid}/` and `uploads/{uid}/{sid}/` and verify empty, recursive Firestore delete of the session, subcollections and `session_status/{sid}`, one content-free `session_deleted` log line, 204 only after storage and Firestore succeed; failures leave `deleting` and a cleanup task finishes it. No tombstone.
Done when: an enumerated test proves no object in any bucket prefix (audio, transcript, report, run artifacts) and no document in any collection or subcollection remains after a full stub flow; the cleanup task is idempotent after an injected failure; exactly one log line exists; CI job `api` (emulator).

## Task 14 — Logging/privacy registration and sentinel test
What it is / what it means: no PHI in logs, one searchable failure line. Traces to R10, AC9.
What changes at a high level: register API fields with `onolys_core.safe_log` (`uid_hash` HMAC, `session_id`, `run_id`, `step`, `status`, `attempt`, `duration_ms`, `auth_kind`, `error_code`, `exc_class`, `request_id`, `code_version`); request-logging middleware (method, route template, status, latency); every failed step/run writes exactly one `status=failed` line with the required keys, `request_id` carried in the task payload, `exc_class` name only.
Done when: a log-capture test over the full stub flow finds none of the sentinel strings from audio/transcript/rating fixtures, tokens or API keys; an injected failure yields exactly one `status=failed` line with `session_id, run_id, step, error_code, exc_class, request_id`; CI job `api`.

## Task 15 — OpenAPI finalisation, `/v1/docs`, contracts, public-api doc, ADR 0020
What it is / what it means: the stable contract SP05 and API-key users rely on. Traces to R2 (docs), R11, D18, AC11, AC17.
What changes at a high level: stable `operationId`s, response models for every error code, `Idempotency-Key` documented, path ids named `{id}`/`{run_id}`/`{report_id}`/`{version}`, no `/presets`, `/dashboard` or top-level `/reports`; `/v1/openapi.json` and Redoc `/v1/docs` without auth (bundle vendored, no external script) with the curl quickstart; `docs/contracts/public/*.schema.json`, `docs/reference/public-api.md`, `docs/decisions/0020-*`; regenerate and commit `api/openapi.json`; notify Lane C that the final client contract is in.
Done when: tests assert both endpoints answer 200 unauthenticated, the docs page references no other host, the path-name and absent-path rules hold, the quickstart curl sequence runs against combined mode, and the regenerate-and-diff check in CI job `api` is clean.

## Task 16 — Dockerfile, dev script, end-to-end acceptance sweep
What it is / what it means: package it and prove every acceptance item together. Traces to R12, D6, AC1, AC2, AC12 and the rest of the AC list.
What changes at a high level: `api/Dockerfile` (one image, ffmpeg, vendored Redoc, `GIT_SHA` build arg, `SERVICE_MODE` entrypoint), a one-command `scripts/dev.sh`-style local run in combined mode with fakes, a complete-flow test over HTTP covering AC2 (incl. `GET /sessions` listing a failed and an in-flight session), two-user isolation across every `{id}` route for token and API-key paths, and a checklist test mapping each AC to a passing test. Image build and boot with `SERVICE_MODE=combined` verified locally; Cloud Run deploy, signBlob, real Cloud Tasks and the Hosting rewrite are SP06/SP09 staging checks and do not block this task.
Done when: `uv run --package onolys-api pytest -q -m "not live"` passes with no GCP/network; the image builds and answers `/v1/healthz`; the dev script runs the quickstart; CI job `api` is green end to end.

## Owner steps (not agent work)
- Tejit: add `ANTHROPIC_API_KEY` to Secret Manager (secret `anthropic-api-key`); not needed for SP04 acceptance on fakes, needed by SP09.
- Tejit/SP06: enable Identity Platform, email verification templates, authorised domains, Google OAuth client; create the GCP resources (SP06) before any staging check.
- Tejit: supply 2-3 real audio samples (10-25 min) for ffprobe/format sanity and the SP09 staging run; keep them out of the repo and the image.
- Tejit: legal stance on backup retention is his and not a blocker (engineering defaults kept: soft-delete 0, PITR off).
