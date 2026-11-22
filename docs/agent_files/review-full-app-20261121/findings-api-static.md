# API static review findings

Counts: critical 0, high 2, medium 7 (+A5/A9), low 15, info 3. No IDOR; Firestore rules sound; no openapi drift.

| ID | Sev | File:line | Bug | Evidence | Fix | Conf |
|---|---|---|---|---|---|---|
| A1 | high | jobs/worker.py:148-149, jobs/stale.py:31, infra/modules/environment/main.tf:66-70 | Busy lease on last attempt returns 200 and drops task; after worker crash session stuck running/validating forever, active_runs slot never released; settle_if_stale only covers transcribing | Probe: TaskRunner.handle(run, retry_count=1) with running run 20s old -> TaskResult(200,"busy"), session stays running | 503 on last-attempt busy or take over expired lease; extend settle_if_stale to validating/running (fail + release_once); heartbeat/shorter lease | high |
| A2 | high | auth/idtoken.py:61,86-87 | Unauth DoS: unknown kid forces sync cert fetch under global lock, no rate limit; fetch failure 503s legit callers | Probe: 5 unknown-kid tokens -> 6 fetches | min refresh interval, negative-cache kids, single-flight outside lock, serve stale | high |
| A3 | medium | repo/firestore.py:96-117,136; routes sessions.py:291, audio.py, runs.py, interviews.py:176, voice/relay.py | Unvalidated path ids/cursor -> Firestore InvalidArgument -> 500 | Emulator: GET /v1/sessions/__x__ 500, /v1/sessions/%2e 500, /v1/interviews/__x__ 500, cursor a/b 500 | Path(pattern=^[0-9a-f]{32}$); map InvalidArgument->NotFound | high |
| A4 | medium | routes/sessions.py:179, routes/audio.py:60, jobs/transcribe.py, repo/limits.py | Caps only count runs/interviews; session create, 300MB upload, ffmpeg, paid STT uncapped/unrate-limited | Static | count STT, cap open sessions, rate-limit POST /sessions,/audio | medium |
| A5 | medium | routes/sessions.py:41, repo/firestore.py:655,733 | n_runs up to 5 costs 1 cap unit | Static; product call | charge n_runs or cap | medium |
| A6 | medium | presets.py:47-65, config/prod/routes.yaml presets.claude | Every preset user-selectable; prod users can pick claude (different vendor, pricier) for 1 unit; unseeded key -> retryable failure, unit not refunded | Stub: {"preset":"claude"} -> 202 | PUBLIC_PRESETS allowlist; check api_key_env at startup | high |
| A7 | medium | jobs/run.py:77-88 | release_once flag set and release in separate steps: leak on failure, double refund under concurrency | Static | single txn with precondition | medium |
| A8 | medium | config.py:80,93, routes/tasks.py:24, api/Dockerfile | ENV defaults local -> AUTH_MODE=fake and no OIDC on /tasks/*; Dockerfile sets no ENV | Static | default prod / require ENV; refuse fake auth on Cloud Run | high(code)/low(exposure) |
| A9 | medium | jobs/interviews.py, routes/interviews.py:140-169, voice/relay.py | Interview <30s refund loop; concurrent creates both reserve | Static | rate-limit, single txn | medium |
| A10 | low | routes/sessions.py:138-161, repo/firestore.py exempt | Interview-linked free first run not bound to relay audio | Static | bind audio or document | medium |
| A11 | low | routes/api_key.py:53-58 | Concurrent POST /api-key -> two active keys, DELETE revokes one | Static race | txn / revoke all | medium |
| A12 | low | routes/speakers.py:103, rating.py:158, audio.py | PHI responses lack Cache-Control no-store | Confirmed /speakers | router-level no-store | high |
| A13 | low | app-wide, errors.py | No request body size limit | 60MB POST /sessions -> 422 after full read | ASGI 413 middleware | high |
| A14 | low | routes/audio.py:126, interviews.py:158 etc | Enqueue failure 500 with state advanced; bad JSON -> 422 invalid_parameters; concurrency limit returns daily_cap_reached; unverified 401 same as bad token; 403 undocumented | Confirmed (b) | map/emit proper codes | high |
| A15 | low | routes/audio.py:78-92, jobs/validate.py find_source | Reissued upload URLs leave old PUTs valid; orphans; PUT works after complete; staged object preferred | Static | delete others, reject PUT after validating | medium |
| A16 | low | audio.py:60-72,120-131 | ffmpeg demuxer autodetect, no protocol_whitelist/rlimits | Static | -protocol_whitelist file, -f, rlimits | low |
| A17 | low | routes/sessions.py:263-282, repo/firestore.py:256-269 | deleting sessions filtered post-page (short pages); cursor deleted -> 422; GET writes | Static | created_at+id cursor | medium |
| A18 | low | routes/sessions.py:54-59 | language only regex-checked (zz accepted), fails at STT | Confirmed | validate vs supported list | high |
| A19 | low | config.py:124, logs.py:75-77 | UID_HMAC_KEY defaults empty, not validated outside local | Static | require in staging/prod | high |
| A20 | low | jobs/run.py:100,190,108-112 | started["llm"] per attempt -> refunds spent unit on attempt 2 | Static | persist on run doc | medium |
| A21 | low | voice/relay.py:96-122,342-356 | No frame size/rate cap, unlimited reconnects | Static | caps | medium |
| A22 | low | routes/speakers.py:126-140 | TOCTOU state check vs non-txn update | Static | txn | low |
| A23 | low | routes/sessions.py:199-247 | Idempotent replay returns deleted session id; lost race 409; non-atomic | Static | verify on replay, batch | medium |
| A24 | low | repo/firestore.py:760-772 | _retry_txn retries any ValueError incl ValidationError, sleeps holding per-uid lock | Static | narrow catch | medium |
| I1 | info | api/openapi.json, web/src/api/schema.d.ts | No drift | regenerated | - | high |
| I2 | info | firestore.rules | Sound; only owner session_status readable; rules test not run | read | - | high |
| I3 | info | routes/*, repo | No IDOR (13 routes 404 cross-user); CORS exact allowlist; generic 500s; API keys sha256 + constant-time | live curl | - | high |
