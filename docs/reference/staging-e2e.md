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

## Task 9: API-key front door and no-rating run

Same sample, staging, deployed sha `698d622`, preset `default`, N=1, language `auto`. Test user created and deleted via Identity Toolkit. Key created with `POST /v1/api-key` (the call the `/api-key` page makes; 201, fields `key_id`, `api_key`, `created`). Every later call used only `X-API-Key`.

Curl steps (the `/v1/docs` quickstart script, key redacted as `<KEY>`; `$AUTH` is `X-API-Key: <KEY>`):

1. `POST /sessions` (Idempotency-Key, `{"language":"auto","n_runs":1,"title":...}`) -> session id
2. `POST /sessions/$SID/audio` -> signed `upload_url` + `required_headers`; `PUT` the file to it
3. `POST /sessions/$SID/audio/complete`
4. `PUT /sessions/$SID/rating` (`final=true`)
5. poll `GET /sessions/$SID` until `awaiting_input`; `GET /speakers`; `POST /speakers/confirm`
6. poll until `report_ready`; `GET /sessions/$SID/reports/1`

| Run | Card | upload-complete -> `awaiting_input` | confirm -> `report_ready` | run doc (started -> ended) | `reasons_audit` | Tips | eaudit artifact |
|---|---|---|---|---|---|---|---|
| A: quickstart as written | change goal + notes (no scores) | not timed | not timed (script has no clock) | 53.5 s, 1 attempt | `partial` (1 item) | 5 | `eaudit.json` 294 B; `run_info.eaudit` present |
| B: no rating | change goal only, `no_rating=true` | 80.1 s | 54.3 s | 53.1 s, 1 attempt | `skipped` (0 items) | 5 | none; `run_info.eaudit` null |

Run B timings: signed PUT 2.5 s, `validating` +1.0 s, `transcribing` +3.6 s after upload-complete. Both runs are well inside the Task 8 target (<= 5 min; 67.9 s at N=1).

Run B report: 4 globals, 10 behaviours, 14 scorecard rows, 5 tips, warnings `short_session`, `reflection_before_client_speech` (no `reasons_audit_*` warning), header `has_clinician_rating=false`, rating coverage 0/14. Run B artifacts under `{uid}/{sid}/runs/{run_id}/`: `paudit.json` (27.5 KB), `tips.json` (7.2 KB), no `eaudit.json`: Task 4's no-eaudit rule holds on staging. Run A (rated card) wrote all three, eaudit included.

Findings:

- **Quickstart PUT failed on staging (fixed in repo, not deployed).** `required_headers` is `Content-Type`, `x-goog-content-length-range`, `Host`; the quickstart sent only Content-Type, so storage answered 400 `MalformedSecurityHeader` (`x-goog-content-length-range` signed but not sent; the script exits 22). The runs above used the same script with the PUT sending all `required_headers` except `Host`. The fix (`api/src/onolys_api/docs.py`, regenerated `api/openapi.json`, test `test_quickstart_put_sends_every_required_header`) lands with this commit; `/v1/docs` on staging shows the fix only after the next deploy. The quickstart also hard-codes `audio/mp4`; for the mp3 sample the request used `audio/mpeg`.
- The quickstart card (`notes` set) counts as a rating (`has_rating=true`), so it gives `reasons_audit=partial`, not `skipped`. `skipped` needs no scores, counts or notes (or `no_rating=true`).
- API-key `DELETE /api-key` with the key itself returns 403 (an ID token is needed). Deleting the Identity Platform user does not revoke the key: it kept authenticating (200) until its `api_keys` doc was removed (then 401).

Cleanup: 3 sessions deleted (204, then 404; includes the session of the failed first PUT), bucket prefix for the user empty, `api_keys`, `users` and `usage` docs for the test user removed (key now 401), test user deleted (lookup returns no account).

## Task 10: forced failures and failure alert

Same sample, staging, deployed sha `a47d593`, one session (N=1, language `auto`, rated card with change goal + notes). Test user created and deleted via Identity Toolkit. Alert policies `Onolys failed step/run (staging)` and `Onolys api 5xx rate (staging)` checked through the Monitoring API before the runs: both exist, enabled, channel `Onolys owner email`.

| # | Run | Result | Run doc | Time |
|---|---|---|---|---|
| 0 | `default` (auto after speakers confirm) | `report_ready`, report v1 | `done`, 1 attempt | 67.3 s |
| 1 | `test-broken-llm` | **session `failed`, `error_code=internal_error`** (expected `upstream_unavailable`): NOT MET on `a47d593`; met on `94c97ec` (see re-check below) | `failed`, 1 attempt (expected both attempts) | 0.9 s (POST -> ended) |
| 2 | `default` (run again, same session) | `report_ready`, report v2 | `done`, 1 attempt | 42.3 s |
| 3 | `test-broken-eaudit` | `report_ready`, report v3; `reasons_audit.status=failed` (0 items); warnings `short_session`, `reflection_before_client_speech`, `reasons_audit_failed`; `run_info.eaudit` null | `done`, 1 attempt | 44.6 s |

Broken-LLM failure (run 1), request_id `4202fe4c62b746d0bbbbb5209c436e3d` (the `X-Request-Id` of `POST /runs`):

- Runbook query (`docs/reference/infra.md`, `jsonPayload.request_id="<id>" AND jsonPayload.status="failed"`, `entries:list`, `orderBy timestamp desc`) returns exactly one line: `onolys-worker-staging`, 22:01:00.348Z, `event run_failed`, `step run`, `error_code internal_error`, `exc_class AllRunsFailed`. Without the `status` term the request_id returns 2 lines (the api request line 22:00:59.405Z and the failed line). With `orderBy timestamp asc` and no time bound the same filter returned nothing; use `desc` or a `timestamp>=` bound.
- Cause chain from the worker logs: paudit `run_index=0` failed with `exc_class=LLMUnavailable` (litellm `NotFound` for the made-up model, 3 route calls in 0.7 s), then `AllRunsFailed`. `error_map._classify` maps `AllRunsFailed` (an `OnolysError`, code `run_failed`) to `internal_error`, not retryable, so there was no second attempt and no `upstream_unavailable`. See Open.
- Alert: one incident, policy `Onolys failed step/run (staging)` (id `3934617429481960380`), alert `0.of8xgp0aphrb`, opened 2026-11-20 22:02:11Z (71 s after the log line), state OPEN at check time (auto-close 1800 s; notification rate limit 300 s). It is the only incident for this policy since the earlier synthetic-line one (21:06:27Z-21:40:50Z, closed). Exactly one `status=failed` line for the run (the broken-eaudit run wrote none: it ends `report_ready`, as required). Email arrival to the owner inbox not checked by the agent (orchestrator to confirm).
- Rate tier: not a factor; the broken routes never reach the provider, runs 0, 2, 3 completed in 42-67 s with 1 attempt, no back-off seen.

Cleanup: session deleted (204, then 404), bucket prefix for the user empty (`onolys-audio-staging`), `users` and `usage` docs removed (no `api_keys` doc was created), test user deleted (lookup returns no account).

### Task 10 re-check on `94c97ec` (broken-LLM outcome met)

Staging sha `94c97ec` (run doc `code_version`), fresh synthetic user, same sample, N=1. Baseline `default` run: `report_ready` (speaker confirm auto-ran; transcript 83.2 s, report 66.7 s). Then `POST /runs {preset:"test-broken-llm"}`, request_id `d369776c07844885b3c3036156b0729b`:

- Session `failed`, `error.code=upstream_unavailable` (retryable). Run doc `failed`, `attempts=2`, `error=upstream_unavailable`, started 22:18:12.731Z, ended 22:18:13.595Z. POST -> `failed` seen by the poll in 8.0 s (the worker retried once ~1 s after the first failure, then ended).
- Runbook query (`request_id` + `status="failed"`, `timestamp>=` bound, `orderBy timestamp desc`) returns exactly one line: `onolys-worker-staging`, 22:18:13.594Z, `event run_failed`, `step run`, `error_code upstream_unavailable`, `exc_class AllRunsFailed`. The request_id alone returns 3 lines: api `request` 202 (22:18:06.845Z), worker `task_retry` (22:18:07.701Z, `upstream_unavailable`), and the `run_failed` line.
- Alert: policy `Onolys failed step/run (staging)` (id `3934617429481960380`). The incident from the earlier run (alert `0.of8xgp0aphrb`, opened 22:02:11Z) was still OPEN when this run failed at 22:18:13Z (inside the 1800 s auto-close window), so no new incident opened; checked via Monitoring API `alerts` (about 2 and 4 min after the log line, still one OPEN alert, opened 22:02:11Z, plus the closed 21:06:27Z-21:40:50Z one). This run's failed line fell inside the open incident. Email not checked by the agent.

Cleanup: session deleted (204, then 404), bucket prefix empty, `users`/`usage`/`api_keys` collections hold no doc for the user (listed, none found), test user deleted (lookup returns no account).

## Resolved

- **Task 10: broken-LLM run ended `internal_error` after one attempt (R3, D3, AC7)**: fixed by `94c97ec` (engine keeps the LLM cause, `error_map` maps a chained `LLMError` to `upstream_unavailable`, retryable). Verified on staging: `failed`, `upstream_unavailable`, 2 attempts (re-check above).

## Open

- The task's 10-25 min recording size is not met: the only real sample is 6.7 min. Run time scales with audio length, so a 10-25 min recording should be re-measured when one is available (the 85 s transcribe step is the part that grows).
- No SP01 p95 figure to compare against (see above).
- `run_info.preset`/`code_version` appear in the run doc and report header; `cost_usd` in evaluation usage is `null`.
- Quickstart on staging still shows the old PUT until the next deploy (see Task 9). A deleted user's API key stays valid until its doc is removed (consider revoking keys on account deletion).

## Task 11: Hosting, CSP and `validate` memory checks

Staging, deployed sha `94c97ec`, test user created and deleted via Identity Toolkit. Numbers and headers only.

### (a) Hosting forwards `Authorization`, does not cache `/v1`: PASS

Through `https://onolys-app-staging.web.app/v1`, 3 repeated authed `GET /sessions`, 2 unauthenticated, 1 bad token, 2 `GET /healthz`, `GET /v1/docs`:

| Call | Status | Cache-Control | X-Cache | Age | Vary |
|---|---|---|---|---|---|
| authed `GET /sessions` x3 | 200, 200, 200 | `no-cache` | MISS, MISS, MISS | absent | `Origin,cookie,need-authorization, x-fh-requested-host, accept-encoding` |
| no `Authorization` x2 | 401, 401 | absent | MISS, MISS | absent | `Origin, x-fh-requested-host, accept-encoding` |
| bad token | 401 | absent | MISS | absent | same |
| `GET /healthz` x2 | 200 | `no-cache` | MISS, MISS | absent | as authed |
| `GET /v1/docs` | 200 | `no-cache` | MISS | absent | as authed |

- Authed calls succeed (200) and the same path without the header is 401, so Hosting forwards `Authorization`. No `HIT`, no `Age` on any `/v1` response.
- Finding (minor): SP05 R8 expects `private, no-cache` on `/v1`; live value is `no-cache` (the `**` header rule in `firebase.json` also covers `/v1`). Not a caching defect, since `no-cache` forces revalidation and Hosting's `Vary` includes `need-authorization`; log as a handed-back item to SP05/SP06 if `private` is wanted.
- HTML `/`: `Cache-Control: no-cache`, `Referrer-Policy: no-referrer`, `X-Content-Type-Options: nosniff`.

### (b) CSP in the browser (web app `web/`, Playwright + Chromium): PASS

Sign-in through the real form (email/password; the app supports it), then `/sessions/{id}` of a session in `transcribing` (Firestore status listener running), then `/login` and the Google button (popup). `securitypolicyviolation` listener on every page plus console capture.

| Check | Result |
|---|---|
| CSP violations (sign-in, dashboard, session page with listener, Google popup click) | 0 |
| Console errors on the app pages | 0 (the popup window itself logged a 404 and a 400 from `onolys.firebaseapp.com`/Google; not CSP, headless popup without a Google session) |
| Hosts contacted | `onolys-app-staging.web.app`, `identitytoolkit.googleapis.com`, `firestore.googleapis.com`, `apis.google.com`, `onolys.firebaseapp.com`, `www.googleapis.com` |
| Session page | rendered the live `transcribing` state (Upload done, Check audio done, Transcribe in progress) |

Live CSP header: `default-src 'self'; script-src 'self' https://apis.google.com; connect-src 'self' https://identitytoolkit.googleapis.com https://securetoken.googleapis.com https://firestore.googleapis.com https://storage.googleapis.com; frame-src 'self' https://accounts.google.com https://*.firebaseapp.com; img-src 'self' data:; style-src 'self'; frame-ancestors 'none'`.

Compared with SP05 R8: `connect-src`, `img-src`, `style-src`, `frame-ancestors`, `default-src` identical (Firestore listener host `firestore.googleapis.com` and Identity Platform hosts exact). Two additions in the live header: `script-src ... https://apis.google.com` (the popup flow loads it; contacted in this run) and `frame-src 'self'`. `www.googleapis.com` is contacted but not in `connect-src` and produced no violation (loaded as a script/frame from an allowed source). Same value is in `firebase.json` for both targets (not a deploy drift). R8 text should be updated to include these.

### (c) `validate` memory with a 300 MB upload: PASS (no OOM)

Upload cap in code: `MAX_UPLOAD_BYTES` = 300 MiB (314,572,800 B); `max_audio_s` 1200 s. Synthetic file (outside the repo, deleted after): WAV PCM 24-bit stereo 48 kHz, sine + pink noise, 1050 s, **302,400,102 B** (the largest practical ~300 MB inside both limits). Worker: 2 Gi, `worker_concurrency` 2, max 3 instances.

| Item | Result |
|---|---|
| Signed PUT of 302 MB | 12.7 s (single), 14 s each (two concurrent) |
| upload-complete -> `validate` done (session reached `transcribing`/`failed`) | about 14 s (single and with two concurrent) |
| Scenario 1 | 1 big upload while a second session (6.7 min mp3) was in `transcribing` (STT poll task every 15 s) |
| Scenario 2 | 2 rounds of 2 concurrent big uploads (4 validates, pairs overlapping) plus the same transcribing session |
| Result of validate | all 5 sessions passed `validate` and went to `transcribing`; they then failed `no_speech` (expected: a tone has no speech) |
| Worker memory, `run.googleapis.com/container/memory/utilizations`, p99 per minute, 22:21-22:31Z | idle 0.20; peak **0.23** of 2 Gi (about 470 MiB), bucket max 0.23-0.24, p50 0.06-0.08 |
| Instance restarts / OOM | none: no `Memory limit` or container-terminated log line, one revision (`00019`), instance count 1 then 2 (scale-out, not a restart) |
| Local measurement of the same steps | `ffprobe` max RSS 52 MB; `ffmpeg` to FLAC 16 kHz mono max RSS 59 MB, 7.8 s, output FLAC 35.6 MB |

The Cloud Monitoring series is sampled about once a minute per instance (2 samples per point), so a 14 s validate does not show above 0.23. Bound by calculation: `validate` downloads the file to `/tmp` (in-memory on Cloud Run) and writes the FLAC there. Per validate about 302 + 36 + 59 = 397 MB; baseline about 470 MiB (0.23); two concurrent validates on one instance about 470 + 2 x 397 = 1,264 MB (about 0.62 of 2 Gi). Margin about 0.38. No fallback applied.

Observation (not part of the task): the second session (real 6.7 min sample, uploaded 22:22:08Z) was still `transcribing` 10 minutes later (poll tasks every 15 s, no error) while the earlier runs of the same sample took 85-176 s. It was deleted during cleanup; cause not investigated (likely Chirp batch latency).

### (d) Phone check (iOS Safari): PENDING OWNER

Sign-in (Google redirect fallback) and a large upload on iOS Safari need a person with an iPhone (Tejit); not attempted by an agent.

### Cleanup

6 sessions deleted (204, then 404), bucket `onolys-audio-staging` prefixes `{uid}/` and `uploads/{uid}/` empty, `users/{uid}` doc removed (no subcollections; `usage`, `api_keys`, `session_status` hold no doc for the user), test user deleted (lookup returns no account), local synthetic file and cached token removed.

## Acceptance sweep (SP09 AC4-AC11)

Written in Task 12. Every value below is copied from a section above; anything not recorded is "not measured". Real sample: `session1-1.mp3` (6.7 min, 405 s); the owner allowed the name to stay in the repo.

| AC | Result | Where recorded |
|---|---|---|
| AC4 | PARTIAL. Web flow upload to `report_ready` done. Confirm to `report_ready` 67.9 s (target <= 300 s: met); upload-complete to `transcript_ready` 84.9 s. The 10-25 min recording criterion is NOT met: only a 6.7-min sample exists, so the 25-min time is not measured | Web / API end-to-end, Timings |
| AC5 | PARTIAL. API-key flow with the curl quickstart gave a report. Run doc 53.5 s (run A) and confirm to `report_ready` 54.3 s (run B), both inside the target. Same 6.7-min limit as AC4; run A confirm to report not timed | Task 9 |
| AC6 | MET. No-rating run B: report with 4 globals, 14 scorecard rows, 5 tips, `reasons_audit.status=skipped`, no `eaudit.json` | Task 9 |
| AC7 | MET on `94c97ec` (not on `a47d593`, which gave `internal_error`). `test-broken-llm`: `failed`, `upstream_unavailable`, 2 attempts, 8.0 s POST to `failed`. "Run again" on `default` gave a report on `a47d593` (run 2, report v2, 42.3 s); it was not repeated after the `94c97ec` failure (the baseline `default` run on `94c97ec` gave `report_ready`, 66.7 s) | Task 10 and re-check |
| AC8 | MET. `test-broken-eaudit`: `report_ready` (v3, 44.6 s), `reasons_audit.status=failed`, warning `reasons_audit_failed` | Task 10 |
| AC9 | MET. `llm.smoke` 6/6, `paudit.cli check` PASS, `onolys_evaluation.check` PASS, `stt.check` PASS (6.7 min sample, 176 s wall) | Live checks |
| AC10 | PARTIAL. Runbook query finds the one `run_failed` line by `request_id` (met). Alert incident opened 71 s after the log line (a47d593 run). Email arrival in the owner inbox: not checked by an agent, owner or orchestrator to confirm. The `94c97ec` failure fell inside the still-open incident, so no new incident | Task 10 and re-check |
| AC11 | PARTIAL. Hosting forwards `Authorization`, no `/v1` caching: PASS. CSP: 0 violations: PASS. 300 MB `validate`: no OOM, worker memory peak 0.23 of 2 Gi: PASS. Phone check (iOS Safari): PENDING OWNER | Task 11 (a)-(d) |

AC1-AC3 (offline, CI) are proven by tests that run in `uv run --package onolys-api pytest -q -m "not live"`:

| AC | Tests |
|---|---|
| AC1 | `api/tests/test_real_flow.py`: `test_real_flow_reaches_report_ready_with_reasons_audit`, `test_stt_start_called_once_across_forced_retry`; `api/tests/test_real_stt.py` |
| AC2 | `api/tests/test_error_map.py`: `test_to_public_table`, `test_wrapper_records_code_and_one_failed_line`, `test_message_is_never_the_exception_message`, `test_stubbed_engine_failure_maps_through_run_and_status_body`; the "Engine errors" section of `docs/reference/public-api.md` is checked against the table by `api/tests/test_engine_errors_doc.py` |
| AC3 | `api/tests/test_run_artifacts.py`: `test_rated_run_leaves_artifacts_run_info_and_header`, `test_no_rating_run_has_no_eaudit_artifact` |

### Measurements for SP06 Task 15

| Item | Value |
|---|---|
| Audio length of every real sample | 6.7 min (405 s, 9.3 MB). 10-25 min: not measured |
| Run start (confirm, card in) to `report_ready`, N=1 | 67.9 s, 67.3 s, 42.3 s, 44.6 s, 54.3 s, 66.7 s across runs (target 300 s) |
| Upload-complete to `transcript_ready` | 84.9 s (Task 8), 80.1 s (Task 9 run B), 83.2 s (`94c97ec` re-check); `stt.check` wall 176 s and 89 s (Chirp varies about 2x) |
| Transcription per audio second | 0.21 s (84.9 s over 405 s); p95 for 25 min: not measured; SP01 p95 figure not recorded anywhere |
| `validate` peak worker memory, 302 MB upload | 0.23 of 2 Gi (about 470 MiB); calculated two concurrent validates about 1,264 MB (0.62 of 2 Gi) |
| Evaluation usage, default preset, N=1 | 8,486 input / 1,303 output tokens (Task 8 run); `onolys_evaluation.check` 24 LLM calls, est. cost $0.96; `cost_usd` in run usage is `null` |
| Anthropic rate-tier back-off | none seen at N=1 (runs completed with 1 attempt); N=6 parallel: not measured |
| Levers used | None of the scaling levers (`max_concurrency`, route timeouts, `worker_max_instances`, worker memory 4 GiB, concurrency 1) were changed. Config changes made: STT gate minimum 5 min (owner decision), `BLOB_SIGNER_EMAIL` set, `staging_alerts=true`, clamp of Chirp `end_offset` 0 (code) |

## Staging test data after the run (listed 2026-11-21, nothing deleted)

Firestore database `staging`, bucket `onolys-audio-staging`, project `onolys`, read-only listing through ADC.

| Store | Remaining |
|---|---|
| Bucket `onolys-audio-staging` | 0 objects (no uploaded recordings left) |
| `sessions` | 3 docs (all one user, created 2026-11-20 22:35-22:37Z, each with a `recordings` subcollection of 1 doc; 2 also have `transcripts` of 1 doc), plus 3 matching `session_status` docs |
| `users` | 6 docs (created 21:02-22:15Z) |
| `usage` | 2 docs |
| `idempotency` | 19 docs (21:39-22:39Z) |

Origin of the remaining documents is not established (the sessions are from the last test user of 2026-11-20, after the Task 11 cleanup was recorded). Deletion is pending an owner or orchestrator decision.
