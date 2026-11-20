# Staging end-to-end results (SP09 R6)

Numbers only. Staging env, project `onolys`, 2026-11-20. Task 8 first run; **the web/API flow is not yet green** (blockers below).

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
| `onolys_core.stt.check` (real owner sample, 6.8 min, 2 speakers) | FAIL on two counts: audio covers 6.7 min vs the 10 min minimum (since lowered to 5 min, owner decision 2026-11-20) (sample is shorter than assumed; `--min-minutes 9` also fails), and one turn has `start_ms > end_ms` (turn `t24`: start 105,960 ms, end 0). Chirp returned a word with `end_offset` 0; `extract_words` does not clamp it. 74 turns, 2 speakers, language `en`, offsets otherwise monotonic. Wall time 89.3 s for 6.8 min of audio (0.22 s per audio second); second run 89 s total |

Needs the `stt-google` extra to run locally (`uv run --extra stt-google --package onolys-core ...`).

## Web / API end-to-end (real sample `session1-1.mp3`, 405 s, 9.3 MB)

Driven through the public API on https://onolys-app-staging.web.app/v1 with a verified test user (created and deleted via Identity Toolkit). Not yet reaching `report_ready`; no timings.

| Step | Result |
|---|---|
| sign-in, create session | OK (202) |
| `POST /audio` (signed PUT) | **500** (two causes in turn): 1) `BLOB_SIGNER_EMAIL` unset (fixed by config above); 2) then `TransportError` from IAM `signBlob`: 403 `ACCESS_TOKEN_SCOPE_INSUFFICIENT`. The api's storage client token is scoped to storage only; `GcsBlobStore._signing_kwargs` sends that token to `iamcredentials` (needs the `cloud-platform` scope). Code fix in `api/src/onolys_api/storage/gcs.py` / `factory.py` |
| Workaround for the run | blob written to `uploads/{uid}/{sid}/{upload_id}` and `session.upload` set with ADC; `POST /audio/complete` OK (202); `validate` passed (0.3 s to `validating`, 5.4 s to `transcribing`) |
| `transcribe` | **failed 1.4 s in**: `step_failed`, `exc_class=OnolysError`, public `internal_error`. Same error text as locally without the extra: `google-cloud-speech is not installed; install the stt-google extra`. The api image (`uv sync --package onolys-api`) does not install `onolys-core[stt-google]`; `api/pyproject.toml` does not depend on it. Not confirmed from the deployed log (messages are not logged); inferred from identical exception class, timing and the dependency files |

Runbook query finds the line by `request_id` (`765b9089a30940fea463e4a37f04416b`, worker, `step transcribe`).

## Open

- Run-start -> `report_ready` (target <= 5 min at N=1), upload-complete -> `transcript_ready` vs SP01 p95: not measured yet. Levers if missed: route `max_concurrency`/timeouts, `worker_max_instances`.
- Blockers to fix before re-running: (1) signBlob scope, (2) `stt-google` extra in the api image, (3) Chirp `end_ms=0` clamp (separate agent), (4) real sample is 6.8 min (the 10-25 min target needs a longer recording or accept a shorter one).
