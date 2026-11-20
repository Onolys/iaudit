# Staging end-to-end results (SP09 R6)

Numbers only. Staging env, project `onolys`, 2026-11-20. Task 8 re-run: **the web/API flow is green** (`report_ready`, 67.9 s run). The first run's blockers are resolved (table below).

## Staging config

- `ADAPTERS=real` already live on api and worker (Terraform `platform_env`; no diff in plan).
- `staging_alerts=true` applied (targeted: `module.staging.google_monitoring_alert_policy.{failed,api_5xx}`, 2 added). The default stays `false`: pass `-var staging_alerts=true` on later applies or the policies are destroyed.
- `BLOB_SIGNER_EMAIL=api-staging@onolys.iam.gserviceaccount.com` added to the api service (Terraform, targeted apply). It was missing; without it signed-URL calls 500 (`AttributeError: you need a private key`). The apply also dropped the CI labels (`commit-sha`, `managed-by`) from the api revision; `GIT_SHA` kept (set to the deployed sha for the apply). The next CI deploy restores the labels.

## Live checks (default preset, `config/staging/routes.yaml`, local run against real providers)

| Check | Result |
|---|---|
| `onolys_core.llm.smoke` | PASS 6/6 routes; 1.1-1.2 s per route (8.5 s cold first call); 54 in / 9 out tokens |
| `paudit.cli check --pack miti@4.2.1` | PASS; count_mae 0.30 (<=1.5), globals_within_1 1.00, bad_output_rate 0.00, p95 latency 20.3 s (<=90), 21,513 tokens/run (<=120,000); 3 runs, 46 s wall |
| `onolys_evaluation.check` | PASS; tips 5 valid (83% quote-valid of 6), `reasons_audit.status=ran`; 30.0 s wall (paudit 13.2, eaudit 26.4, tips 16.7); 24 LLM calls, est. cost $0.96 |
| `onolys_core.stt.check` (real owner sample, 6.7 min, 2 speakers, re-run) | PASS; audio covers 6.7 min (min now 5, owner decision 2026-11-20), 77 turns, 2 speakers, language `en`, offsets monotonic (first run failed on `end_ms=0`, fixed in 21649aa). Wall 176 s for 6.7 min of audio (0.44 s per audio second; the first run took 89 s, so Chirp latency varies about 2x). Input was `audio/canonical.flac` of the staging run below, via `gs://` URI |

Needs the `stt-google` extra to run locally (`uv run --extra stt-google --package onolys-core ...`).

## Web / API end-to-end (real sample `session1-1.mp3`, 405 s, 9.3 MB)

Driven through the public API on https://onolys-app-staging.web.app/v1 with a verified test user (created and deleted via Identity Toolkit), deployed sha `698d622`, preset `default`, N=1, language `auto`. Real signed-URL upload, no ADC workaround.

| Step | Result |
|---|---|
| sign-in, create session | OK (202) |
| `POST /audio` + signed PUT (9.3 MB) | OK (200, 200); PUT 1.7 s |
| `POST /audio/complete` | 202; `validating` +1.9 s, `transcribing` +6.8 s |
| `transcribe` -> `transcript_ready` / `awaiting_input` | +84.9 s after upload-complete; 2 speakers (S1 38 turns, S2 39 turns) |
| rating card `PUT /rating` final (change goal + 4 globals scored 3) | 202 |
| speakers confirm (run start) | 202; `running` +0.9 s |
| run -> `report_ready` | **67.9 s** after confirm (target <= 5 min: met); run doc `done`, 1 attempt |

Report contents (counts): 4 globals, 10 behaviours, 14 scorecard rows, 5 tips, `reasons_audit.status=ran` (4 items), rating coverage 4/14, within-one share 1.00, avg abs global difference 0.75, warnings `short_session`, `reflection_before_client_speech`. `run_info` has `evaluation`, `paudit`, `eaudit` parts; artifacts `paudit.json` (28 KB), `eaudit.json` (1.7 KB), `tips.json` (6.9 KB) written under `{uid}/{sid}/runs/{run_id}/`. Evaluation usage: 8,486 input / 1,303 output tokens.

### Timings

| Interval | Seconds |
|---|---|
| signed PUT (9.3 MB) | 1.7 |
| upload-complete -> `validating` | 1.9 |
| upload-complete -> `transcribing` | 6.8 |
| upload-complete -> `transcript_ready` | 84.9 |
| speakers confirm (run start, card already submitted) -> `report_ready` | 67.9 |

SP01 p95 gate for 25 min of audio: no p95 value is recorded anywhere to compare against; the 6.7 min sample took 84.9 s (0.21 s per audio second), consistent with the local check (0.22 s, 89 s; the 176 s `stt.check` re-run shows 2x variance).

### Resolved blockers (first run)

| Blocker | Status |
|---|---|
| signed URL `signBlob` 403 `ACCESS_TOKEN_SCOPE_INSUFFICIENT` | Resolved, bad0fd6 (cloud-platform-scoped creds) |
| `BLOB_SIGNER_EMAIL` unset | Resolved (Terraform, see config) |
| `google-cloud-speech` missing in api/worker image | Resolved, 929f219 (`onolys-core[stt-google]`) |
| Chirp word `end_offset` 0 gives `start_ms > end_ms` | Resolved, 21649aa (clamp) |
| STT gate minimum 10 min vs 6.7 min sample | Resolved, 27713e1 (minimum 5 min, owner decision) |

Test data: the test session was deleted through `DELETE /sessions/{id}` (204, then 404), the staging bucket prefix for the user is empty, and the test user was deleted (lookup returns no account).

## Open

- The task's 10-25 min recording size is not met: the only real sample is 6.7 min. Run time scales with audio length, so a 10-25 min recording should be re-measured when one is available (the 85 s transcribe step is the part that grows).
- No SP01 p95 figure to compare against (see above).
- `run_info.preset`/`code_version` appear in the run doc and report header; `cost_usd` in evaluation usage is `null`.
