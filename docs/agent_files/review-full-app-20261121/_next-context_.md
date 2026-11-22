# Next context — review/full-app (updated 2026-11-22)

## Fix run (dev-code light mode) — IN PROGRESS
Owner reversed "no fixes": fix ALL bugs FX1–46, add tests FX52–56, then cleanup FX47–51.
Plan:
- Phase A, two parallel tracks:
  - API track: worktree /root/projects/onolys/iaudit/.worktrees/review-full-app-api, branch review/full-app-api. Batches A1..A8 run serially:
    - A1 FX3
    - A2 FX4+FX53
    - A3 FX10+FX28
    - A4 FX11+FX12+FX54
    - A5 FX42+FX46+FX13+FX44
    - A6 FX43
    - A7 FX14+FX25+FX27+FX52
    - A8 FX26+FX29+FX30+FX31+FX41
  - Web track: this worktree, branch review/full-app. Batches W1..W8 run serially:
    - W1 FX1+FX55
    - W2 FX2+FX15
    - W3 FX6+FX23+FX35
    - W4 FX7
    - W5 FX16-19+FX56
    - W6 FX20-22+FX24
    - W7 FX32-34
    - W8 FX36-40
- Phase B: merge review/full-app-api into review/full-app; then cross-area FX5, FX8, FX9, FX45 one at a time.
- Phase C: cleanup FX47–51, then dev-review, then the Ship? question.
Done:
- API: A1 eea5c0c; A2 ef182b9 + b305ab4; A3 fbf5542 + 1f519b9; A4 19280a9 + 2bc3ddd + 7115b7d. M16 mutant left surviving.
- Web: W1 532cc8c; W2 3fd592a + 160fcc6; W3 b4904b9 + 3a012fd + 09ff3a0; W4 e03669a; W5 bc62d31 + 2f204a0 + 55c92c5 + 009134b; W6 6b81e85 + 160165f + 5682f97 + 8f2f425; W7 40c8d70 + 81d066e + 0d5342a.
- W8: ffe2722 (FX34 follow-up) + 3924e7f + f36555e + 8bac9e3 + 6becdca. FX38: no change needed.
Web track: all batches W1–W8 done.
- 3c2be5f: outdated flow/layout tests fixed after FX20/FX32 (test-only).
- A5: c1ac02f + 3876575 + 1d867ed + f3f4a9b.
- A6: b7116e0 (FX43).
- C1: 6112ddc + 96428e4 + a42fa04 + 350cb0e (FX47, FX50, FX51, e2e lint).
Owner clarified caps (2026-11-22):
- Each flow has ONE limit, and it is daily: the AI interview flow uses AI_CAP_DAY, the evaluation flow uses EVAL_CAP_DAY.
- Monthly caps are removed.
- Max 1 active run per user.
- An interview = 1 unit from the AI budget and includes its 1 rating, which does not count toward the eval limit.
- A5b: 1c59118 + 45b9033.
  - Monthly caps gone, including in infra. GET /usage has no `month`; `period` is `day` only.
  - MAX_ACTIVE_RUNS default is now 1.
Phase B web follow-up: remove `monthly_cap_reached` and usage `month` from:
- web/src/api/{errors.ts, errors.test.ts, schema.d.ts}
- features/session/{timeline.ts, timeline.test.ts, SessionPage.tsx, SessionPage.test.tsx}
- features/usage/{usage.ts, usage.test.ts}
- mocks/stateMachine{,.test}.ts
- __fuzz_review__/api-lib.property.test.ts
FX45 Phase B: an interview session gets only 1 rating. POST /runs after its free run is currently charged to EVAL; FX45 "final, no run again" should reject it.
- A7: 53f76ab (oidc tests broken by FX4's 60s floor) + 07640a5 + 8f12352 + 0263603 + d6fd08b.
  - ENV is now required.
  - UID_HMAC_KEY is required outside local/test.
  - 1 MiB body limit.
  - no-store on /v1.
- A8: 6cfdab1 + 89db194 + d67010a + 428ec95 + 6206453 + aafdd56 + 0857079. API track: all batches done.
For review:
- FX29: late PUT not rejected (keeps the validated original, sweeps the rest).
- FX30 language list is ISO 639-1 + fil/yue; does STT accept locales like en-US?
- A23 same-key race xfail kept; it moves to @flaky in FX49.
- Merge 90034fc, no conflicts. Contract sync 5577fae. Clock test 9a9dd42.
- All work is now on review/full-app. The review/full-app-api worktree can be removed at the end.
- FX5 b276297 (API only).
- Check before ship: `ruff format --check` flags 4 api files. Check whether CI runs it and whether this branch caused it.
- FX8 3287fba (api) + 8c6df07 (web). upload_incomplete appears after 15 min + 60 s.
- FX9 5f736e9 (web only). The interview ends on the next page load; the sweep handles a closed tab.
- FX45 2a8b1c0 (api) + b18d525 (web).
- FX45 follow-ups 4835f00 + 8361e66 + 8c20400 + fa05d00.
  - For review: the second final PUT check is read-then-write, not a txn, so concurrent double submits could slip through.
All bugs FX1–46 are done.
C2 DONE (2026-11-22): FX49 8d25bcb (A23 xfail dropped, 5/5 pass, both race tests @flaky); FX48 7766001 (36 e2e tests, live.spec removed); web-e2e CI job 69114ec; api worktree + branch removed. CI runs no `ruff format --check`; 7 api files unformatted, all from this branch (left as-is). `npm run lint` passes.
Owner task: make `web-e2e` a required status check (no aggregator job / ruleset).
Review DONE: round 1 NEEDS_CHANGES (2451e0a) → fixes 49e576c, 1986bf4, f2e9276 (privacy guard), 0cb7758 (vitest excludes e2e_review); round 2 NEEDS_CHANGES (4b502c2) → 25c1073; round 3 PASS (artifact review-2026-11-22-1700.md, to commit).
Owner decisions pending (review notes): cap post-LLM system-failure refunds per day; force n_runs=1 on free interview run; FX44 duration-only binding; dead caps.reserve/reserve_run/release_run.
Running: dev-ship (no Ship? per owner memory; push, CI runs tests).
Then: FX5, FX8, FX9, FX45 serially; then FX48, FX49, the web-e2e CI job; then dev-review.
Next: A7, A8, then merge, then Phase B.
Owner tasks:
- FX43: unmount ANTHROPIC_API_KEY from the worker unless claude is enabled. To enable claude, set ENABLED_EXTRA_PRESETS=claude in infra.
Deferred to the end:
- FX48 trim.
- FX49 (api).
- The web-e2e CI job.
Owner-only tasks:
- FX38: after deploy, confirm Google popup/redirect sign-in on staging and prod shows no CSP violation.
Note: FX45 must rewrite the flow tests that expect "Run again" after a successful report.
- Check in cleanup: eslint reports 21 require() errors on web/e2e_review/*.cjs. Does `npm run lint` (eslint .) fail in CI?
Follow-ups to carry:
- Non-hex ids now return 422 (FX10). In W8/FX40, check the web shows "not found" for a 422 on a session id.
- A14 leftovers (concurrency-limit code, unverified-401 distinction) go in A8.
- FX2: submit now saves the pending draft first; check this in review.
Notes:
- Emulator: `npx -y firebase-tools@15.37.0 emulators:exec --config api/firebase.json --only firestore --project demo-onolys '<cmd>'`.
- e2e runs rewrite e2e-shots PNGs; revert before commit.
- Don't `pkill -f vite`.
- The E3/W19 test.fail stays until FX32.
- Sample report was dropped from the verified nav (follows D1).

Read this first in the next session. The owner will fix the bugs themselves. Nothing is pushed.

## State
- Worktree: /root/projects/onolys/iaudit/.worktrees/review-full-app, branch `review/full-app` (local only, unpushed), rebased on origin/main d83e6be (PR #48).
- Review is DONE. App code is UNCHANGED (the partial FX1 edit to web/src/auth/next.ts was reverted). No bug fixes, by owner decision.
- The fix run (dev-code) was started then STOPPED by the owner: "no need to fix the bugs, just note them, I'll fix later".

## Files in this folder (docs/agent_files/review-full-app-20261121/)
- `FINDINGS.md`: the master list. 56 deduped rows FX1–FX56 grouped P0 (7) / P1 (17) / P2 (17) / owner decision (5, now resolved below) / test cleanup (10). It maps each owner UX decision to its FX rows. **Start here.**
- `review-2026-11-22-0100.md`: dev-review (Bug Hunter / Security / Architect) verdict NEEDS_CHANGES, plus the CI fit table for the test suites.
- Raw sources: `findings-web-static.md` (W1–32), `findings-api-static.md` (A1–24), `findings-e2e.md` (E1–24, screenshots in `e2e-shots/`), `findings-fuzz-mutation.md` (F1–9, mutation scores, M1–21).
- `RUN.md`: how to run the app locally (mock mode; live-ish mode = Firestore emulator + api stub adapters + fake auth; open at localhost:5173, not 127.0.0.1).

## Tests already added (committed on branch)
- Playwright suite `web/e2e_review/`: 78 specs (76 mock, 2 @live). Run with `cd web && npm run e2e -- --trace off`, about 1 min. Known bugs are marked `test.fail()` with their E#/W# id; remove the marker when the bug is fixed.
- API fuzz: `api/tests/test_fuzz_review.py`, `api/tests/test_schemathesis_smoke.py`. Already split per PR #48 (unit cases xdist-safe, emulator cases `firestore`-marked). Known bugs are strict xfail with their id.
- Web property tests: `web/src/__fuzz_review__/*.property.test.ts`, using `it.fails` for F5/F6/F7.
- Mutation configs: `[tool.mutmut]` in `api/pyproject.toml`, `web/stryker.conf.json`, plus the doc `docs/testing/fuzz-and-mutation.md` (manual/nightly only).
- New dev deps: hypothesis, schemathesis (api); fast-check, Stryker, @playwright/test 1.65.1 (web).

## Test-suite cleanup TODO (not done; FINDINGS FX47–FX51 + review AR5–AR7, N1–N3)
1. FX47/AR5: the e2e `shot()` helper writes 33 PNGs into tracked `docs/agent_files/.../e2e-shots/` on every run. Change it to take shots only when `E2E_SHOTS=1`, into `test-results/`. Move the RUN.md "Mode B" recipe into `docs/testing/local-setup.md` and repoint the README, `playwright.config.cjs` and fuzz-and-mutation.md.
2. FX48/AR6: trim Playwright from 76 to ~35. Keep only real-browser behaviour: nav by auth phase, back/forward/reload, mobile layout and horizontal scroll, real file-length precheck, E17 unmount autosave, E3 next crash, beforeunload. Delete the specs that duplicate vitest (auth-action.spec vs AuthAction.test.tsx; signup/login/forgot vs auth/pages.test.tsx; happy path/delete/sample vs flows/flows.test.tsx), the W17 spec (can't reproduce) and live.spec.cjs.
3. Add a `web-e2e` CI job in `.github/workflows/ci.yml`:
   - Triggers: `needs: changes`, `if: needs.changes.outputs.web == 'true'`, parallel to `web`.
   - Browser: cache `~/.cache/ms-playwright` keyed on the @playwright/test version, then `npx playwright install --with-deps chromium`.
   - Playwright config when CI is set: forbidOnly, retries 0, github reporter, @live excluded.
   - Workers 2; upload test-results/ on failure only; shard only if the run exceeds 3 min.
   - Blocking, about 2–3 min.
4. FX49/AR7: mark the A11/A23 race tests in `test_fuzz_review.py` (~:293, :304; currently non-strict xfail) `@pytest.mark.flaky` so they run in the non-blocking `api-flaky` job. Delete `test_isolation_random_ids_between_users` (~:325), which duplicates `test_isolation.py`.
5. FX50/N1/N3: pin fast-check and Stryker exactly (the repo pins exact versions). Consider dropping Stryker from devDeps and using `npx -p` (it adds ~2.3k lockfile lines to every CI npm ci). Re-encode the e2e audio fixtures (3.4 MB, mainly ten-min.mp3) to under 1 MB.
6. FX51/N2: Stryker `inPlace: true` mutates tracked files, so set it to false. Gitignore web/reports/, api/mutants/ and the dirs mutmut copies into api/. Fix the `[tool.mutmut]` comment, which points to a nonexistent tests/MUTATION.md.
7. FX52–56: add tests for surviving mutants (oidc.py has zero coverage; idtoken sub bounds; limits.py cap overrides; run.py release_once/report validation; guards; parseErrorBody). Best done together with the matching bug fix.
8. When each bug is fixed: remove its test.fail / xfail / it.fails marker.

## Owner UX decisions (MVP: keep simple, but prod-quality)
- D1 nav by auth state:
  - Signed out: Log in, Sign up, Sample report.
  - Signed in and verified: Sessions, New session, Settings, Sign out + email.
  - Unverified: Verify email + Sign out.
  - Loading: brand only.
- D2 signup: show-password toggle AND confirm-password field; keep the 8-char minimum.
- D3 after password reset: "Password updated", then the login page with email prefilled.
- D4 never-uploaded sessions: "Upload incomplete" with Resume upload + Delete.
- D5 Google sign-in on an email that has a password account: message "use your password".
- D6 interview reload: warn before leaving (beforeunload). If they leave, the interview ends; no rejoin. Basic design.
- D7 live status listener drop: auto-retry with backoff, then poll; show an error after a retry limit.
- D8 defaults:
  - Sample report public.
  - Signup says the email exists; forgot-password hides whether it exists.
  - Keep ?next through verify-email.
  - Dashboard auto-refreshes in-progress chips.
  - Forgot-password with a malformed email: "enter a valid email".
  - Keep it simple.

## Owner product decisions (FX42–46 resolved)
- FX42 n_runs: charge 1 unit per run (n_runs=3 costs 3 units; blocked if not enough left).
- FX43 presets: public allowlist. Users get the default Gemini preset only; claude via config/admin only; test-* presets in staging only.
- FX46 caps: ONE limit per user flow, nothing else.
  - AI interview: 1 unit at start, counted even if never rated. It covers rating its own recording (keep the A10 free first run, but bind the audio to the relay recording).
  - Upload flow: free until the user clicks "Run rating", then 1 unit. Plain session create or upload doesn't count.
  - Keep the <30s interview refund, capped at 3 refunds per user per day.
- FX45 rating: once submitted it's FINAL, with no edit and no "Run again".
  - A successful report is final.
  - A system failure (provider outage, worker crash) refunds the unit and shows "Try again", which re-runs the same submission.
  - A bad file shows "Upload a different file".
- FX44: keep A10, bind the audio.

## Other notes
- Nightly (`.github/workflows/nightly.yml`): green 15 of 15 runs, and the live test really runs. Owner: don't touch. Failing scheduled notifications come from other repos (crontick Security Audit, kyro Nightly); the owner chose not to fix those.
- The suggested fix order, when the owner wants it, is in FINDINGS.md: P0 first (FX1 auth phase/nav, FX2 rating data loss, FX3 stuck sessions, FX4 JWKS DoS, FX5 stale coded_span, FX6 Run-again dead end, FX7 live updates).
- Owner preferences: sub-agents on sonnet, max 2 concurrent, commit per task, CI time bounded and shardable, no test bloat.
