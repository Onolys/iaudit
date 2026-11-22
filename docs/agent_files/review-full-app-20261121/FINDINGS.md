# Consolidated fix list — main app (web/ + api/), review/full-app
Sources: findings-web-static (W), findings-api-static (A), findings-e2e (E), findings-fuzz-mutation (F, M), review-2026-11-22-0100 (BH, S, AR, N). Deduped; reviewer-adjusted severities (A2 high, A6 medium, A8 low, W19/F5/E3-redirect low). Owner decisions D1-D8 map below.

Counts: P0 7 | P1 17 | P2 17 | Owner decision 5 | Test cleanup 10 (56 rows).

## P0 — fix now
| ID | Sources | Sev | Area | Problem | Fix | UX |
|---|---|---|---|---|---|---|
| FX1 | AR1, W1, E1, E1b, E1c, E2, E9, E20, W7, E3(crash), W4, W5, W23 | high | web | Auth state derived in 4+ places; nav shows protected links signed-out/unverified; 404 assumes signed in; sign-out doesn't navigate; no errorElement; cache/uploads survive user change | AuthProvider `phase`; Layout `NAV[phase]`; guards on phase+withNext; one `useSignOut()`; NotFound by phase; root errorElement; clear cache + upload registry on uid change; catch signOut failure | D1 |
| FX2 | W2, E17 | high | web | Unmount flush then dispose drops edits <2s old (Back/redirect) -> data loss | Dispose after `await flush()` or let final flush ignore `disposed` | - |
| FX3 | A1, BH4 | high | api | Busy lease on last attempt returns 200, drops task; crash leaves session running/validating forever, run slot never released; stale settle only covers transcribing and keys off bumped `updated_at` | 503 on last-attempt busy / take over expired lease; extend `settle_if_stale` to validating/running (fail + release_once); stale cutoff not `updated_at` | - |
| FX4 | A2, M2, M3 | high | api | Unauth DoS: unknown kid forces sync cert fetch under global lock; fetch failure 503s legit callers | Min refresh interval, negative-cache kids, single-flight outside lock, serve stale; tests for kid refetch + TTL boundary | - |
| FX5 | BH1 | high | api+web | Clearing `coded_span` never removes old session value -> re-runs score stale span | Final save and change_goal always set `coded_span` to span or None (or run reads rating revision) | - |
| FX6 | BH2 | high | web | Pre-transcript failures (`internal_error`, `upstream_unavailable`) show "Run again" -> always 409 dead end | Pick recovery from transcript_ready; none -> "Upload a different file" | - |
| FX7 | AR2, W16, W25, E22(live-updates) | high | web | Listener error/null doc -> one GET, updates frozen; dashboard chips never refresh; 3 hand-rolled freshness paths | Fallback `["session-detail", id]` query w/ refetchInterval + retry/backoff; resubscribe N times then error; dashboard `refetchInterval: anyInProgress ? 10_000 : false`; keep list on fetchNextPage error | D7, D8 |

## P1 — real bugs, fix in this PR
| ID | Sources | Sev | Area | Problem | Fix | UX |
|---|---|---|---|---|---|---|
| FX8 | AR3, W30, W17, E16 | med | web+api | Abandoned uploads stay "Uploading" forever; no resume; pick race; navigate after leave; double-click Start errors | Lazy stale check -> `upload_incomplete` (non-terminal); chip + Resume upload + Delete; shared pick hook w/ stale guard + "Checking file"; mounted guard | D4 |
| FX9 | AR4, W18, W29 | med | web+api | Interview rejoin conflicts with owner rule; double Start talking leaks engine/mic/socket; silent `ended` | beforeunload warn; mount-on-live -> "Interview ended" + POST end; server resume only for in-page reconnect; busy guard; message on `ended` | D6 |
| FX10 | A3, F1, F3, F4 | med | api | Bad path ids/cursor -> Firestore InvalidArgument / decode -> 500 | `Path(pattern=^[0-9a-f]{32}$)` (+length); map InvalidArgument -> NotFound; cursor decode -> 422 | - |
| FX11 | A7, A20, M11 | med | api | release_once not atomic (leak / double refund); `started["llm"]` per attempt refunds spent unit | Single txn w/ precondition; persist flag on run doc; test released flag persisted | - |
| FX12 | BH3 | med | api | Transient Google error in validate stage not retried -> session permanently fails | Map `_GOOGLE_TRANSIENT` to `upstream_unavailable` for run stage | - |
| FX13 | A9 | med | api | Interview <30s refund loop; concurrent creates both reserve | Rate-limit; single txn | - |
| FX14 | S1 | med | api | Uvicorn logs full traceback + ResponseValidationError `input` -> PHI to Cloud Logging | `--log-config` dropping exc_info, or outer ASGI middleware | - |
| FX15 | W3 | med | web | `saver.cancel()` clears dirty; failed final PUT never autosaved | cancel only clears timer / re-mark dirty in catch | - |
| FX16 | W6 | med | web | main.tsx chain has no catch -> blank page on boot failure | Catch + minimal "Can't start the app, reload" | - |
| FX17 | W8, W9 | med | web | AuthAction maps any pre-check failure to "invalid link"; already-verified user gets invalid-link copy | Invalid only for invalid/expired code; else retry+network msg; verified user -> "Already verified" + Continue | - |
| FX18 | W10 | med | web | `signUp` rejects if verification email send fails after account created | Swallow send failure in signUp; VerifyEmail has Resend | - |
| FX19 | W11, W13, E4, E4b, E5, E6, E8 | med | web | Unmapped auth codes -> "Something went wrong"; no client validation on Login/Signup; redirect-result error swallowed; no aria-invalid | Map missing-email/password, account-exists-with-different-credential ("use your password"), popup-blocked, etc.; empty/format checks; surface redirect error; aria-invalid | D5 |
| FX20 | (owner) | med | web | Signup lacks show-password and confirm-password | Add toggle + confirm field; keep 8-char min | D2 |
| FX21 | (owner), W8 | med | web | Reset flow doesn't show success/prefill | "Password updated" -> /login with email prefilled | D3 |
| FX22 | W14, E13 | med | web | Forgot: `sent` never reset (success + error together); malformed email shows success | Reset `sent` on submit; "enter a valid email" for invalid-email | D8 |
| FX23 | W15 | med | web | Start/Run again re-enabled before status flips -> second POST /runs | Also lock while `run.isSuccess` until doc state changes (SessionPage, ReportPage) | - |
| FX24 | W20 | low | web | `next` lost through email-link verify; resend cooldown resets on reload; "I've verified" no busy; note never clears | Include `next` in continue URL; persist cooldown (sessionStorage); busy state | D8 |

## P2 — low / hardening, fix if cheap
| ID | Sources | Sev | Area | Problem | Fix | UX |
|---|---|---|---|---|---|---|
| FX25 | A8, A19 | low | api | ENV defaults local (fake auth, no /tasks OIDC); UID_HMAC_KEY not validated | Default prod / require ENV; refuse fake auth on Cloud Run; require key in staging/prod | - |
| FX26 | A11, A22, A23, A24 | low | api | Races: two api keys, speakers TOCTOU, replay returns deleted id, `_retry_txn` retries ValueError under lock | Txn / revoke all; verify on replay; narrow catch | - |
| FX27 | A12, A13 | low | api | No `Cache-Control: no-store` on PHI; no body size limit | Router-level no-store; ASGI 413 middleware | - |
| FX28 | A14, F2, F8, F9 | low | api | Wrong/undocumented codes (enqueue 500, bad JSON 400, 409/422/403 not in openapi) | Map proper codes; update openapi | - |
| FX29 | A15, A16 | low | api | Reissued upload URLs stay valid, PUT after validating; ffmpeg autodetect no whitelist | Delete others, reject late PUT; `-protocol_whitelist file`, `-f`, rlimits | - |
| FX30 | A17, A18 | low | api | Deleting sessions filtered post-page; GET writes; language only regex-checked | created_at+id cursor; validate vs supported list | - |
| FX31 | A21 | low | api | Relay: no frame size/rate cap, unlimited reconnects | Add caps | - |
| FX32 | W19, F5, E3(next), E12 | low | web | `readNext` accepts control chars (`/\t/evil.com`), `/auth/action`, login loops; no open redirect (crash only, covered by FX1) | Reject control chars / origin check; reject `/login`, `/signup`, `/auth/action` | - |
| FX33 | W12 | low | web | Google button no busy; popup cancel shown as error | Shared busy flag | - |
| FX34 | W21, W22 | low | web | Email-change signOut reliance; hardcoded APP_HOSTS | `fbSignOut` in catch, compare emails; same-origin/env | - |
| FX35 | W24 | low | web | Default retry:1 retries 4xx | `retry` fn skipping ApiError <500 | - |
| FX36 | W26, E19 | low | web | Clipboard rejection/no "Copied"; modal focus not restored; confirm closes on error | `.then/catch` + feedback; restore focus | - |
| FX37 | W27, W28 | low | web | Hash selection via window not router; behaviours cell shows run 1 not mean | `useLocation().hash`; prefer `mean` | - |
| FX38 | W31 | low | web | CSP frame-src may lack content.googleapis.com | Verify Google sign-in on staging; add host if violated | - |
| FX39 | W32 | low | web | Escape during in-flight delete hides failure | Ignore Escape while busy | - |
| FX40 | E7, E14, E21, E23, F6, F7 | low | web | Long email overflows; AuthAction verify error above live prompt; mock-only unknown-session spinner; reset time no TZ; formatElapsed NaN; sliceCodePoints negatives | Wrap; replace prompt; error card; show TZ; guard non-finite/negative | - |
| FX41 | E22(CORS) | low | api | Local Mode B: CORS `allow_headers` blocks fake-blob PUT | Add upload headers to dev allow list | - |

## Needs owner decision
| ID | Sources | Sev | Area | Question | Recommended default |
|---|---|---|---|---|---|
| FX42 | A5 | med | api | n_runs up to 5 costs 1 cap unit | Charge n_runs units |
| FX43 | A6, A8 | med | api | `claude` preset user-selectable in prod (other vendor, pricier, PHI to 2nd vendor; key mounted on worker; unseeded key not refunded) | `PUBLIC_PRESETS` allowlist; check api_key_env at startup; unmount key unless enabled |
| FX44 | A10 | low | api | Interview-linked free first run not bound to relay audio | Bind audio, or document |
| FX45 | E24 | info | web | Rating form still editable under "Your report is ready" | Keep if edit+run-again intended |
| FX46 | A4 | med | api | Session create/300MB upload/ffmpeg/STT uncapped, no rate limit | Need numbers: open-session cap, rate limit, STT count |

## Test-suite cleanup
| ID | Sources | Sev | Area | Problem | Fix |
|---|---|---|---|---|---|
| FX47 | AR5 | med | web | e2e writes 33 screenshots into tracked docs each run; refs to agent_files RUN.md | `E2E_SHOTS=1` -> test-results/; move Mode B recipe to `docs/testing/local-setup.md` |
| FX48 | AR6 | med | web | Playwright duplicates vitest (~76 specs) | Keep real-browser only (~35); delete rest |
| FX49 | AR7 | med | api | Non-strict xfails (A23, A11) in blocking api-emulator; duplicate isolation test | `@pytest.mark.flaky`; delete `test_isolation_random_ids_between_users` |
| FX50 | N1, N3 | low | web | fast-check/Stryker `^` ranges, +2.3k lockfile lines; 3.4MB audio fixtures | Pin exact / `npx -p`; re-encode <1MB |
| FX51 | N2 | low | both | stryker inPlace mutates tracked files; reports/mutants not gitignored; dead MUTATION.md ref | gitignore; fix comment |
| FX52 | M8 | med | api | `auth/oidc.py` 63 mutants, 0 coverage (/tasks auth) | Unit tests for audience/issuer/email |
| FX53 | M1, M4, M5, M6, M7 | low | api | idtoken/deps survivors: sub bounds, skew, AUTH_PROJECT fallback, dummy hash, seen cap | Add boundary tests |
| FX54 | M9, M10, M12, M13, M14, M15, M16 | med | api | limits.py/run.py survivors: cap override branches, invalid report passes, rating/coded_span/language args, deadline, retry boundary, resume | Add tests (pair with FX5/FX11/FX12) |
| FX55 | M17, M18 | low | web | guards.tsx loading/redirect survivors | Tests (rewrite with FX1) |
| FX56 | M19, M20, M21 | low | web | parseErrorBody malformed entries, failureAction guards, per-code auth messages | Add tests |

## Owner UX decisions -> FX rows
| # | Decision | FX rows |
|---|---|---|
| D1 | Nav by auth state (signed out / verified + email + Sign out / unverified) | FX1 (+FX55) |
| D2 | Signup show-password + confirm, 8-char min | FX20 |
| D3 | Password reset -> "Password updated" -> login email prefilled | FX21 |
| D4 | Stale uploads: "Upload incomplete" + Resume + Delete | FX8 |
| D5 | Google on existing password email: "use your password" | FX19 |
| D6 | Interview: beforeunload warn; leave = ends, no rejoin | FX9 |
| D7 | Listener drop: backoff retry, then poll, then error | FX7 |
| D8 | Defaults: sample public; signup/forgot enumeration split; keep next through verify; dashboard refresh; forgot malformed -> "valid email" | FX24, FX7, FX22 (sample public/enumeration: no change) |
