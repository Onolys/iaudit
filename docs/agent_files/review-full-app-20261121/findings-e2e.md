# E2E browser review: web/ main app (base a10373f)

Method: Playwright + Chromium against the real app. Mock mode (`dev:mock`: MSW + fake auth) for everything; live-ish mode (Firestore emulator + api stub adapters + `dev:live`, fake auth) for the main flow and a few gating checks. Real Firebase Auth cannot run locally, so invalid-email / missing-password / too-many-requests / valid `/auth/action` codes / Google / cross-tab sign-out are NOT covered. Everything below is encoded in the durable suite `web/e2e_review/` (see its README): each known bug is a `test.fail()` carrying its ID, so it flips red once fixed.

Suite: 78 specs (76 mock, default; 2 `@live`, excluded by default). Mock run: 76 passed (22 of them are expected-fail bug markers), 1.0 min with 4 workers, `fullyParallel`, shard-friendly. Screenshots: run with E2E_SHOTS=1.

No open redirect and no crash-free-path regressions found for `?next=` apart from E3. Main happy path (signup > upload > transcribe > speaker > rating > report > settings > dashboard) works in mock mode with zero console errors/failed requests.

## Findings

| ID | Sev | Page / route | Steps to reproduce | Expected vs actual | Screenshot | Static | Conf |
|---|---|---|---|---|---|---|---|
| E1 | high | every page, signed out (/login, /signup, /forgot-password, /sample-report, /nope) | Open /login signed out | Expected: Log in / Sign up / Sample report only. Actual: header shows Sessions, New session, Sample report, Settings; clicking Sessions/New session/Settings bounces to /login?next= | screenshots: run with E2E_SHOTS=1 | W1 | high |
| E1b | med | /verify-email (unverified) | Sign up | Expected: minimal header (Verify email / Sign out). Actual: full app nav; clicks redirect back to /verify-email?next= | screenshots: run with E2E_SHOTS=1 | W1 | high |
| E1c | low | /auth/action (all states) | Open /auth/action?mode=resetPassword&oobCode=x | Actual: full app nav on a password-reset page | screenshots: run with E2E_SHOTS=1 | W1 | high |
| E2 | low | /nope signed out | Open /nope | Actual: "Back to your sessions" CTA for a signed-out visitor | screenshots: run with E2E_SHOTS=1 | W1 | high |
| E3 | high | /login?next=/%09/evil.com | Signed in, open that URL (or log in with it) | Expected: land on /. Actual: React Router "External navigation is not allowed" thrown in render, default error screen, blank page with no header/nav, no way back. No request to evil.com was made (no open redirect). `//evil.com`, `https://evil.com`, `/\evil.com`, `javascript:` all fall back to `/` correctly | screenshots: run with E2E_SHOTS=1 | W19, W7 | high |
| E4 | low | /signup | Submit empty form | Expected: email-required message. Actual: only "Use at least 8 characters for your password."; form is noValidate | screenshots: run with E2E_SHOTS=1 | W11 | high |
| E4b | med | /signup | Valid password, empty email, submit | Expected: email error. Actual (fake auth): empty address sent to service, account created, lands on /verify-email. Real Firebase would answer `auth/missing-email`, which is unmapped ("Something went wrong") per W11 | n/a | W11 | med (real Firebase untested) |
| E5 | low | /signup | Email `foo` or `a@b`, password ok | Actual (fake auth): accepted, verify page says "sent to foo". No client-side format check; real Firebase answer untested | n/a | W11 | low |
| E6 | low | /signup, /login errors | Trigger any validation error | Expected: field marked `aria-invalid`. Actual: none; only a role=alert summary above the form | screenshots: run with E2E_SHOTS=1 | none | high |
| E7 | low | /verify-email | Sign up with a 254-char email | Actual: address does not wrap; page scrolls sideways, buttons stretch off-screen (desktop and 390px) | screenshots: run with E2E_SHOTS=1 | none | high |
| E8 | med | /login | Submit empty form | Expected: "Enter your email/password". Actual: "That email and password don't match" (no client check; real Firebase would give `auth/missing-password`, unmapped) | screenshots: run with E2E_SHOTS=1 | W11 | high (mock), med (real) |
| E9 | low | Settings > Sign out | Sign out from Settings | Expected: /login. Actual: /login?next=%2Fsettings (guard bounce), so the next login drops the user into Settings | n/a | none | high |
| E12 | low | /login?next=/auth/action | Log in with that next | Actual: lands on dead-end "This link isn't valid" page | n/a | W19 | high |
| E13 | low | /forgot-password | Enter `foo`, submit | Actual: shows "If an account exists... we've sent a link" (unknown address shows the same by design) | screenshots: run with E2E_SHOTS=1 | W14 | high |
| E14 | low | /auth/action?mode=verifyEmail&oobCode=bad | Click "Verify my email" | Actual: error banner shown above the unchanged "Confirm your email address" prompt and still-enabled button | screenshots: run with E2E_SHOTS=1 | none | high |
| E16 | low | /sessions/new (mock) | Double-click Start | Actual: PUT to uploads.mock.invalid 403 and POST /audio/complete 409 logged as console errors; session still proceeds | n/a | W30 (related) | med |
| E17 | high | /sessions/:id rating form | Type in Change goal, immediately history.back() (no blur), then forward | Expected: text kept. Actual: edit lost (never saved) | n/a | W2 | high |
| E19 | low | /settings | Create API key, click Copy | Expected: "Copied" feedback. Actual: none (secret is shown once) | screenshots: run with E2E_SHOTS=1 | W26 | high |
| E20 | low | all pages, 390px (iPhone 13) | Open /login | Header wraps to 3 rows (189px tall). No horizontal scroll on any page (login, signup, forgot, sample report, 404, verify, dashboard, new session, session+rating form, report, settings, interview) | screenshots: run with E2E_SHOTS=1 | none | high |
| E21 | med | /sessions/<unknown id> (mock mode) | Signed in, open /sessions/s_does_not_exist | Expected: error card. Actual: stays on "Loading session..." for 20s+, no request, no error. Live api mode shows an error alert (spec passes there) so mock-only unless another path leaves a missing doc | screenshots: run with E2E_SHOTS=1 | W16 (related) | high (mock) |
| E22 | med (dev-only) | live mode: /sessions/new > Start | Run RUN.md live-ish setup, upload any file | Expected: upload completes and worker runs. Actual: browser PUT to `/v1/_fake_blob/...` blocked by CORS (preflight 400 `cors_rejected`; api `allow_headers` lacks the upload's required headers), 3 retries, "The upload didn't finish. Retry upload". Page also shows "Live updates stopped" right after create (W16: one GET then no more updates). Local Mode B cannot reach transcript/report | n/a (test: live.spec.cjs) | W16 | high |
| E23 | low | /settings | View usage | "Daily limit resets at 12:00 AM" has no time zone | screenshots: run with E2E_SHOTS=1 | none | med |
| E24 | info | /sessions/:id after report ready | Open completed session | Rating form with enabled "Submit rating / No rating" buttons is still shown under "Your report is ready". May be intended (edit rating + run again); confirm with owner | screenshots: run with E2E_SHOTS=1 | none | low |

Counts: high 3 (E1, E3, E17); med 5 (E1b, E4b, E8, E21, E22); low 14 (E1c, E2, E4, E5, E6, E7, E9, E12, E13, E14, E16, E19, E20, E23); info 1 (E24).

## Other behaviour verified OK (no bug)

Deep links to every protected route (/, /sessions/new, /sessions/:id, reports, interviews, settings) bounce to /login with `next` preserved and never render protected content, including in samples taken during auth loading; back/forward after logout shows only /login; refresh keeps `next`; Sample report public; /verify-email signed out goes to /login; wrong password and unknown user give the same message; Enter key, uppercase/padded email, double-click signup, existing email (any case) message with "Log in instead"; weak and whitespace passwords rejected; verify page resend cooldown (60 s) works; unverified protected clicks redirect to /verify-email with next, and next is restored after "I've verified"; `/auth/action` incomplete/unknown/bogus codes show the right pages in every mode, `continueUrl=https://evil.com` never followed; no console errors or failed requests on the mock happy path; new-session precheck (bad type blocked, <10 min warning); API key create/dismiss gating; interview start page loads cleanly.

## W# status

- Confirmed in browser: W1 (E1, E1b, E1c), W2 (E17), W7 (E3, no errorElement), W11 (E4, E4b, E8 in mock; real Firebase codes untested), W14 (E13, malformed email part), W16 (E22, "Live updates stopped" right after create), W19 (E3 crash; E12; no open redirect observed), W26 (E19 copy feedback; focus restore not checked).
- Not reproduced: W17 (picking short then long, and long then short, file in quick succession ended with the correct check; local file duration reads are too fast to lose the race), W24 (no GET for an unknown session id was observed at all in mock mode, so retry count could not be measured).
- Not browser-testable here (need real Firebase Auth, failure injection, mic, or multi-tab auth): W3, W4, W5, W6, W8, W9, W10, W12, W13, W15, W18, W20 (reload part), W21, W22, W23, W25, W27, W28, W29, W30, W31, W32. Several are covered by vitest unit tests (valid `/auth/action` codes etc.).
