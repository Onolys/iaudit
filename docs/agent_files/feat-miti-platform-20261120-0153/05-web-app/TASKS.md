---
status: draft
summary: 14 tasks for SP05 — scaffold + MSW mocks + auth first, then session page, upload, rating card, speaker gate, transcript, report, dashboard/sample, settings, hosting/privacy, generated types, flow tests.
date: 2026-11-20
---
# Tasks: SP05 web app — `web/` (app.onolys.com)
Source of truth: [PRD.md](PRD.md). Lane C. Built on MSW mocks from day one (D5); no Playwright, no axe in v1 (D12, r8): flow tests are Vitest + Testing Library + MSW, plus one manual click-through on the PR preview (SP00 R3). Every task's tests run in the `web` CI job (SP00: `npm ci`, typecheck, lint, vitest, build; skipped until `web/package.json` exists, so Task 1 is what turns it on). Sync points: SP04's committed `api/openapi.json` and SP03's `report.schema.json`; until they are committed, fixtures use the PRD's documented shapes and Task 13 switches to the generated types.

| # | Task | Depends on | Status |
|---|---|---|---|
| 1 | Scaffold `web/`, tokens, router shell, lint rules, `web` CI job turns on | none | done |
| 2 | API client, error mapping, MSW handlers, fixtures, state machine, status-listener seam | 1 | done |
| 3 | Auth: sign-up, login, reset, verify-email, guards, token retry | 1, 2 | done |
| 4 | Session page: status listener, derived timeline, error cards, delete | 2, 3 | done |
| 5 | Create session form and uploader | 4 | done |
| 6 | Rating card with autosave and `miti-items` parity | 4 | done |
| 7 | Speaker gate and "Change who the clinician is" | 4 | done |
| 8 | Transcript view with code-point segmenter | 2 | done |
| 9 | Report page | 8 | in-progress |
| 10 | Dashboard and `/sample-report` | 3, 9 | todo |
| 11 | Settings and API key | 3 | todo |
| 12 | Hosting config, privacy and CSP checks, ADR 0021 | 1 | todo |
| 13 | Switch to generated types and `gen:api` staleness check | 2, 9, SP04 T1, SP03 T1 (contracts committed) | todo |
| 14 | Flow tests, staging deploy check, manual preview click-through | 5, 6, 7, 9, 10, 11, 12, 13 | todo |

Parallel lanes: Tasks 1, 2, 3 are the shared scaffolding (app shell, MSW, auth); one person does them, in order, and pushes as soon as green. After Task 3, three people can work at once: (a) the session chain: Task 4, then 5, 6 and 7 are independent screens on the session page and can split between people; (b) the report chain: Task 8, then 9, then 10 (needs 9 for the sample report); (c) Tasks 11 and 12 (settings, hosting/privacy) which touch separate files. Task 8 only needs Task 2, so it can start as soon as MSW fixtures exist. Task 13 waits for SP04 and SP03 to commit their contracts; Task 14 is last. Cross-lane syncs: SP00 PR preview needs Task 1 buildable; SP06 staging deploy needs Task 12.

## Task 1 — Scaffold `web/`, tokens, router shell, lint rules, `web` CI job turns on
What it is / what it means: the empty but buildable app everything else lands in. Traces to R1 (routes), R8 (no remote fonts, a11y lint), D2, D3, D10.
What changes at a high level: `web/` with React 19, Vite, TS, vitest, Testing Library; react-router with the route table as placeholder pages and the app layout (landmarks, focus to `h1` on route change); TanStack Query with short in-memory `gcTime`; copied landing tokens and self-hosted Inter; ESLint with `eslint-plugin-jsx-a11y` and a rule banning `dangerouslySetInnerHTML`; `.env.example` listing the `VITE_*` variables; npm scripts `typecheck`, `lint`, `test`, `build`, `dev:mock`, `dev:live`.
Done when: Vitest tests cover the route table renders each placeholder and focus moves to `h1` on navigation; a lint test proves `dangerouslySetInnerHTML` fails; the CI `web` job runs npm ci, typecheck, lint, vitest and build green (first run proves the job un-skips).

## Task 2 — API client, error mapping, MSW handlers, fixtures, state machine, status-listener seam
What it is / what it means: the mock-first foundation (D4, D5). Traces to R7, R4 (error table), D5, D8.
What changes at a high level: `openapi-fetch` wrapper (base `/v1`, bearer from a token provider, `Idempotency-Key` on `POST /sessions` only, `public-error-response` parsing, one forced-refresh retry on 401); error-code to plain-message map; MSW handlers with a state machine emitting `state` plus the four flags, drafts vs final rating, cap-held start, failure injection by title incl. the three transcription codes; typed fixtures (N=1 report, no-rating report, `reasons_audit` failed, UTF-8 edge transcript, 3-speaker gate); fake auth (`Bearer test:<uid>`); a status-subscription interface with an in-memory emitter for mock mode. Types here come from the PRD's documented shapes.
Done when: Vitest unit tests cover error mapping for every code, the 401 retry (once, then sign-out signal), `Idempotency-Key` only on create, and the state machine walking every state; fixtures validate against the report schema once available (otherwise a typed shape check). Run in `web`.

## Task 3 — Auth: sign-up, login, reset, verify-email, guards, token retry
What it is / what it means: the entry flow and route protection. Traces to R1, R2, D8, AC5.
What changes at a high level: `firebase/auth` modular only; email+password and Google (popup, redirect fallback); forgot-password with the same confirmation always; plain-text error mapping (min 8 chars, email in use offers login); `?next=` honoured; `/verify-email` with spam-folder note, Resend with 60 s cooldown, "I've verified" and focus auto-check, both forcing token refresh; guards (unauthenticated, unverified, 401-after-refresh sign-out); sign-out clears the query cache. Fake auth mode for mocks.
Done when: Vitest page tests cover each form, the same reset message for any email, cooldown, guard redirects, the second-401 sign-out and that an unverified user cannot reach `/`. Run in `web`.

## Task 4 — Session page: status listener, derived timeline, error cards, delete
What it is / what it means: the page every in-flight session lives on. Traces to R4 (status, failure, delete), D7, D14, AC6a, AC6b, AC8.
What changes at a high level: Firestore `onSnapshot` on `session_status/{id}` (memory cache, `getFirestore(app, VITE_FIRESTORE_DATABASE)`, emulator via `VITE_FIRESTORE_EMULATOR`), attached right after create, unsubscribed on leave, one `GET /sessions/{id}` fallback on error or permission-denied; timeline derived from `state` and flags with `aria-live` text and sub-labels from `step`; `awaiting_input` copy and the cap-reached message with Start; error card per code with the reference id and the right recovery button; delete confirm dialog. Page has slots for the upload, rating card and speaker gate.
Done when: a table-driven Vitest test covers the timeline for every `state` x flag combination including `awaiting_input` with speaker missing, rating missing and both; tests cover permission-denied fallback, no polling while a session runs, each error card and recovery, and delete. Run in `web`.

## Task 5 — Create session form and uploader
What it is / what it means: from file to running transcription. Traces to R3, D6, D18, AC2.
What changes at a high level: form with audio drop/choose, language dropdown (`auto` default, `en-US`, `en-GB`), optional title, no Advanced section; advisory pre-checks (size over 300 MB with the "export m4a/mp3" message, extension, duration from audio metadata: over 25 min blocks, under 10 min warns); `POST /sessions`, `POST …/audio`, navigate at once; app-level uploader using XHR with exactly the returned `required_headers`, progress, cancel, `beforeunload` guard, auto-retry with a fresh URL up to 2 times, then "Retry upload"; `POST …/audio/complete`. Measure-and-record: read the SP01 gate result (ADR 0017); if diarization failed with `auto`, remove it and default to `en-US`.
Done when: Vitest tests cover each pre-check, a mocked XHR proves progress, cancel, exact headers and the retry count, and the language list matches the recorded gate result. Run in `web`.

## Task 6 — Rating card with autosave and `miti-items` parity
What it is / what it means: the in-app rating input, filled while transcription runs. Traces to R4 (rating card), D13, D15, AC6.
What changes at a high level: card with change goal (required), optional coded from-to span, four globals (1-5 or not rated, reason, optional timestamped example), ten behaviour codes (count, note), and the separate notes box labelled as not parsed; soft-cap counters that warn without blocking; debounced draft `PUT` (about 2 s, on blur, `keepalive` flush on page hide) with a "Draft saved" indicator; restore from `GET …/rating`; "Submit rating" and "No rating" send `final:true`; per-field `rating_invalid` messages; static `protocol/miti-items.ts`.
Done when: Vitest tests cover a parity check against the copied `rating.schema.json`, counters past 1,000/3,000 without blocking, autosave debounce and flush, reload restoring the draft, a draft not satisfying the gate, final vs no-rating payloads and 422 mapping. Run in `web`.

## Task 7 — Speaker gate and "Change who the clinician is"
What it is / what it means: the one machine-guess confirmation. Traces to R4 (speaker gate), AC6b.
What changes at a high level: gate shown when `transcript_ready` and not `speaker_confirmed`; a card per speaker with 3 plain-text sample lines and "This is the clinician"; with more than 2 speakers all listed plus the "everyone else is the client" note; `POST …/speakers/confirm`; in `report_ready` or `failed` a link reopens it with the button "Save and run again". Independent of the rating card.
Done when: Vitest tests cover the 2- and 3-speaker fixtures, the confirm call, the reopen path starting a new run, keyboard operation and that sample lines render as text only. Run in `web`.

## Task 8 — Transcript view with code-point segmenter
What it is / what it means: the XSS-safe, offset-correct transcript. Traces to R4 (transcript), D11, AC4, Risks (offset drift).
What changes at a high level: transcript from `GET /sessions/{id}/transcript` with role labels and `start_ms` timestamps; `lib/codepoints.ts` index map and `lib/spans.ts` `buildSegments` (copied idea from `frontend/`, D2); selected instance id in the URL hash drives scroll and pulse highlight; segmenter verifies the quote matches the slice in dev and degrades to an unhighlighted quote list in prod.
Done when: Vitest unit tests cover emoji and combining-accent highlighting, overlapping spans, a mismatch degrading safely, and text-only rendering; the lint rule from Task 1 stays green. Run in `web`.

## Task 9 — Report page
What it is / what it means: the evidence-linked report, driven by report JSON. Traces to R4 (report), D17, AC3.
What changes at a high level: route by integer version; two-pane desktop with sticky transcript, mobile single column with a Transcript tab; sections in `layout[]` order, unknown sections skipped, major `schema_version` mismatch notice; header with run-details line, plain version select, Run again, and "Add or edit my rating → Run again"; scorecard chips (text plus tone, Onolys-only when unrated); disagreement blocks only for global `differs` and count `flagged`; globals, behaviour table with instance chips and "+N more"; summaries vs reference levels with "not pass marks"; `reasons_audit` by status; tips; method note; `warnings[]` as quiet notices; N>1 shows value with "based on N runs".
Done when: Vitest page tests cover every fixture (rated, no-rating then add rating then v2, `reasons_audit` failed, differs-only count with no block), chip tone and text, chip click scrolling to the transcript, unknown section skipped and version mismatch. Run in `web`.

## Task 10 — Dashboard and `/sample-report`
What it is / what it means: the landing screen and the no-backend demo. Traces to R5, R1 (sample), D16, AC3a.
What changes at a high level: paginated session list with status chips, "Report vN" link, "Load more", usage line and over-cap state disabling Run again and Start; empty state with one line, New session, "See a sample report"; public `/sample-report` rendering the bundled N=1 fixture and transcript through the Task 9 components with a "Sample" banner and no controls.
Done when: Vitest tests cover chips for every state, in-flight and failed rows linking to the session, pagination, the cap state and the empty state; a sample-report test asserts zero network requests. Run in `web`.

## Task 11 — Settings and API key
What it is / what it means: key management, usage and sign out. Traces to R6, D9, AC7.
What changes at a high level: key metadata; Create, Regenerate (confirm) and Revoke; secret shown once in a modal with copy and an "I've stored it" gate, held only in dialog state; "API docs" link to `/v1/docs` with a `curl` placeholder example; usage; sign out; account-removal text using a config placeholder for the contact address.
Done when: Vitest tests prove the secret appears once and is absent after dismiss or reload, `localStorage`/`sessionStorage` and a console spy never see it, regenerate confirm, docs link target and sign-out clearing the cache. Run in `web`.

## Task 12 — Hosting config, privacy and CSP checks, ADR 0021
What it is / what it means: the deploy shape and the privacy guarantees as tests. Traces to R8, D1, D10, AC8, AC10.
What changes at a high level: `web/firebase.json` with the `/v1/**` rewrite before the SPA fallback, CSP and the other headers, a staging target; a config-driven check of every host the app can reach; ADR `0021-web-app-hosting-and-sharing.md`. Measure-and-record in the ADR: whether `style-src 'self'` needs hashes after a production build (fallback: add hashes); exact CSP hosts for popup and listener are confirmed on staging in SP09.
Done when: Vitest unit tests assert `firebase.json` carries the CSP and rewrite order, that fetch, Firestore and Auth configuration only target hosts in `connect-src`/`frame-src`, no analytics code or storage of app data, no PHI in titles or console output; production build checked for inline styles. Run in `web`.

## Task 13 — Switch to generated types and `gen:api` staleness check
What it is / what it means: replace documented-shape types with the real contracts. Traces to R7, D4, AC1.
What changes at a high level: `npm run gen:api` runs `openapi-typescript` on the committed `api/openapi.json` and `json-schema-to-typescript` on `report.schema.json`; fixtures re-typed and validated against the schema; a CI staleness check fails if generated files differ. Runs when SP04 and SP03 have committed; record any shape mismatches fixed.
Done when: Vitest tests validate every report fixture against `report.schema.json`; typecheck is green against generated types; the `web` job fails on a deliberately stale generated file and passes on a clean run.

## Task 14 — Flow tests, staging deploy check, manual preview click-through
What it is / what it means: the end-to-end proof without Playwright (r8). Traces to R9, D12, AC2, AC9, AC10.
What changes at a high level: Vitest + Testing Library + MSW flow tests: sign-up, verify, upload, speaker and rating filled during transcription, report; no-rating run, add rating, run again; failure then Run again; reasons-audit failed note; cap reached then Start; delete; API key once-only; sample report offline. Then a manual click-through on the SP00 PR preview and on SP06 staging (incl. a phone check for iOS Safari upload and Google popup, recorded in the PR).
Done when: all flow tests pass in the `web` job, `typecheck`, `lint`, `test`, `build` pass with no network, and the manual preview results (real API in `SERVICE_MODE=combined`, a visual accessibility look) are recorded.

## Owner steps (not agent work)
- Tejit adds the `app.onolys.com` DNS records from SP06's output; adds the domain to Identity Platform authorised domains; adds `https://app.onolys.com/__/auth/handler` to the Google OAuth client redirect URIs; customises verification and reset email templates.
- SP06 (infra lane): Hosting sites `onolys-app` and `onolys-app-staging`, Cloud Run `api` unauthenticated invocation, GCS CORS (PUT, headers `Content-Type`, `x-goog-content-length-range`), and the deploy workflow for `web/` with `VITE_FIREBASE_*` and `VITE_FIRESTORE_DATABASE`.
- Tejit provides the Onolys contact address for account-removal requests before launch, and sample real self-ratings for the rating-form check.
