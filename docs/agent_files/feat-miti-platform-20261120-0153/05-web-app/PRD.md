---
status: draft
summary: React+Vite+TS web app `web/` for app.onolys.com — auth, upload, speaker/rating confirm, job status, interactive report, dashboard, API-key settings; typed client from `api/openapi.json`, mock mode first; Firebase Hosting with same-origin `/v1` rewrite.
date: 2026-11-20
---
# PRD: SP05 web app — `web/` (app.onolys.com)

Repo/branch: Onolys/onolys (local `iaudit`) / `feat/miti-platform` · Depends on: SP04 `api/openapi.json` + `docs/contracts/public/*` (contract; builds against mocks until API is live), SP03 `engines/evaluation/schemas/report.schema.json` (the report contract; TS types generated from it), SP02 `rating.schema.json`/`report.yaml`; SP06 for Hosting site, DNS, Identity Platform config · Owns: `web/**` (incl. `web/firebase.json`, `web/src/api/` generated client, `web/src/mocks/`, `web/e2e/`), `docs/decisions/0021-web-app-hosting-and-sharing.md`

## TL;DR
A single-page React app that is a thin, typed consumer of the public `/v1` API (nothing else touches PHI). Identity Platform web SDK is used for sign-in only; every byte of session data goes through our API (or signed GCS URLs the API hands out). Served by Firebase Hosting on `app.onolys.com` with `/v1/**` rewritten to the Cloud Run `api` service (same origin). A mock mode (MSW + typed fixtures) lets the whole flow be built and tested before SP04 ships.

## Problem
Clinicians need a no-help path: sign up, upload a recording and self-rating, confirm two machine guesses (who is the clinician; what the rating says), wait a few minutes, read an evidence-linked report, and re-run. The report must be readable, non-judgmental ("Onolys disagrees, here's why"), and must never leak PHI into analytics, logs, browser storage, or the auth provider.
Verified: `frontend/` is React 19 + Vite 8 + TS + vitest with eaudit-specific contract/transport and span segmentation (`contract/spans.ts`, `app/ClaimText.tsx`, `tokens/`) [verified: `frontend/package.json`, `frontend/src/app/ClaimText.tsx`]; landing tokens (teal `#0b5f5a`, score good/fair/low chips with text labels, Inter) live in `onolys-landing/src/styles/tokens.css` [verified]. SP04 `GET /sessions/{id}/transcript` supplies turns (added in the reconcile pass).

## Goals / Non-Goals
**Goals:** all of scope below working end to end against the SP04 stub API in `SERVICE_MODE=combined`; usable on a phone; WCAG 2.1 AA basics; 100 MB upload with progress and recovery; zero third-party scripts.
**Non-goals (v1):** PDF export, teams, billing, email, trends, transcript editing, non-English UI/report, account-deletion endpoint, audio playback synced to transcript, offline, i18n, push/SSE.

## Requirements
**R1 Routes** (react-router, SPA):
| Route | Auth | Content |
|---|---|---|
| `/signup` `/login` `/forgot-password` | public | email+password forms, "Continue with Google"; links between them; `?next=` honoured |
| `/verify-email` | signed-in, unverified | "Check your inbox", Resend (cooldown 60 s), "I've verified" (reload + force-refresh token), auto-check on tab focus |
| `/` | verified | Dashboard (R5) |
| `/sessions/new` | verified | Upload form (R3) |
| `/sessions/:id` | verified | Status timeline + gate steps + errors + delete |
| `/sessions/:id/reports/:version` | verified | Report (R4); `version` = integer |
| `/settings` | verified | API key, usage, sign out |
Guards: unauthenticated → `/login?next=`; unverified → `/verify-email`; API 401 after one forced token refresh → sign out → `/login`. Unknown id → API 404 → friendly "not found" (never reveals other users).

**R2 Auth.** `firebase/auth` modular only (no analytics/other SDKs). Persistence: SDK default (IndexedDB); app stores nothing else. Every request calls `user.getIdToken()` (SDK refreshes ~5 min before expiry); a 401 triggers exactly one `getIdToken(true)` retry. Email verification: `sendEmailVerification` with continue URL `/verify-email`; after verification the cached token still lacks `email_verified`, so force-refresh before calling the API (API requires `email_verified=true`). Google sign-in: popup, redirect fallback on mobile/popup-blocked; `authDomain = app.onolys.com` (Hosting serves `/__/auth/*` on the custom domain). Forgot password: always shows the same confirmation (no account enumeration). Open sign-up, no allowlist. Error messages mapped to plain text (wrong password, weak password ≥8, email in use → offer login). Sign-out clears the query cache.

**R3 Create session** (`/sessions/new`): one form, then a three-step submit:
1. Fields: audio (drag-drop/choose; mp3 wav m4a webm ogg; ≤100 MB), rating (textarea paste **or** file docx/pdf/xlsx/txt ≤10 MB, or "No rating — just rate my session"), language dropdown (`Auto-detect` default + list from a static BCP-47 allowlist), "coded from–to" (mm:ss pair, optional, sent as `coded_span{from_s,to_s}` seconds; helper text: "only if you rated part of the recording"), change goal (required unless rating contains it; hint), Advanced (collapsed `<details>` disclosure): `n_runs` (1–5, default 1) and `preset` select, both rendered from `GET /v1/presets` (hidden if only one preset is listed); title optional. [RESOLVED: API accepts `n_runs` and allowlisted `preset`; web shows them under Advanced (reconcile pass)]
2. Client pre-checks (advisory; server is authoritative): size, extension/MIME, duration via `HTMLAudioElement` metadata (>25 min blocks with message; <10 min shows the warning that globals are unreliable).
3. Submit: `POST /sessions` (`Idempotency-Key` = UUID per form instance) → `POST …/audio` → `PUT` file to signed URL with **XMLHttpRequest** (fetch has no upload progress), exact signed `Content-Type`, progress bar with MB/%, cancel button, `beforeunload` guard while uploading → `POST …/audio/complete` → rating `PUT`/file upload (can run in parallel with the audio PUT) → navigate to `/sessions/:id`. Upload failure/expiry (15 min URL): request a fresh URL and retry the whole object up to 2 times automatically, then show "Retry upload" on the session page (session exists in `created`). Chunked resumable upload is out of v1 [DEFERRED]. The pasted rating and the file are held in React state only (never localStorage).

**R4 Session page + report.**
*Status:* poll `GET /sessions/{id}` every 3 s with `If-None-Match`; pause when the tab is hidden; back off 3→6→12→30 s on network/5xx; stop at `awaiting_*`, `report_ready`, `failed` and resume after a confirm. Timeline renders `steps[]` (Upload · Check audio · Transcribe · Confirm speaker · Read rating · Confirm rating · Rate session · Report) with `aria-live="polite"` status text and copy "Usually under 5 minutes — you can close this tab and come back; your report will be here." Elapsed-time shown, no fake percentages beyond API `progress`.
*Speaker gate* (`awaiting_speaker_confirm`): per speaker a card with the 3 sample lines (plain text) and "This is the clinician"; submit `POST …/speakers/confirm`. No editing.
*Rating gate* (`awaiting_rating_confirm`): editable form from `GET …/rating/parsed`: change goal, coded span, 4 global selects (1–5 or "not rated"), 10 count inputs (int or blank), per-item reasons textarea, notes; fields named in the parsed rating's `field_flags[{path, code}]` (`reason_not_in_source`, `value_unverified`) or left null are highlighted ("we couldn't find this — fill in or leave blank" / "check this against your document"); parsed `status` `unreadable|invalid` → paste prompt; `rating_unreadable` → "paste your rating instead". Submit `POST …/rating/confirm` (partial allowed).
*Failure:* error card with plain message per code table (`unsupported_audio`, `audio_too_long`, `audio_too_large`, `audio_unreadable`, `rating_unreadable`, `upstream_unavailable`, `daily_cap_reached`, `invalid_state`, `rate_limited`, generic), the `request_id` as "reference", and: failure at `validate`/`transcribe` → "Upload a different file" (new session, params prefilled); later failures → **Run again** (`POST …/runs`).
*Delete:* confirm dialog stating audio, transcript, rating, all report versions are removed permanently → `DELETE` → dashboard.
*Report* (`/sessions/:id/reports/:version`; version→report id via `GET …/reports`): two-pane on desktop (report left, transcript right, sticky), single column with a "Transcript" bottom sheet/tab on mobile. Sections in the order of the report's `layout[]` (`{section, title, items?}`, SP03 R7; sections the UI does not know are skipped): (1) header from `header{change_goal, protocol{label}, models, n_runs, rating_coverage}` + `created_at`: change goal, MITI 4.2.1, models, date, version switcher (v1…vN with date + models; default latest), **Run again**; (2) `scorecard[]`: per item "You | Onolys | difference chip" from `clinician.value`, `onolys{value,mean,min,max,values[]}` and `diff{signed,abs,direction,status,within_one?}` (chip text like "Onolys +1" from `signed`; `status` `agree|differs|flagged|not_rated|no_onolys_value` picks the tone; colour never alone; no rating → Onolys column only, "–" elsewhere); (3) "Onolys disagrees, here's why" blocks only for `differs|flagged` items, from `globals[]`/`behaviours[]` `explanation{headline, body[], onolys_lines[], clinician_support_lines[]}` (lines carry `{turn_id,start,end,quote}`; each a button → scrolls/highlights in transcript; Onolys's lines vs lines supporting the clinician are labelled; the headline text comes from the report, not hard-coded); (4) globals (`globals[]`: Onolys `score` + `reason` + `evidence[]` lines, your score + reason); (5) behaviour counts table (`behaviours[]`: `clinician_count`, `onolys_count{mean,min,max,values[]}`) with instance chips from `instances[]` (`{id,turn_id,start,end,quote,rationale}`; `instances_total` above the number shown → "+N more") (click → jump to and pulse highlight in transcript; keyboard operable; note "these are Onolys's instances; a tally-only self-rating can't be matched line by line"); (6) `summaries[]` (`clinician`/`onolys` value + label vs `reference{fair,good}`, `note`) vs reference levels with copy "reference levels, not pass marks" and fair/good ticks; (7) `reasons_audit` (`status` `ran|partial|skipped|failed`; per item `claims[]` with eaudit `verdict` shown as supported / partly supported / not supported (`contradicted`) / not enough evidence (`insufficient_evidence`); `out_of_scope` claims are not shown; evidence lines by `role`; `skipped` (no-rating run) hides the section; `partial` adds a note); (8) `tips[]` (3–5 by `rank`; `item_id` tag, `observation`, `quote{turn_id,start,end,text}`, `alternative`, `why_it_matters`); (9) `method{statement, limits[], citation}` note (shown verbatim; `not_official_miti_coding` is always true). N>1: values shown as mean with range ("2.7, runs 2–3"), instances from the representative run (labelled). Unknown future sections are skipped; `schema_version` (stored by SP04 as `report_schema_version`) major mismatch shows "This report was made by a newer version — refresh". `warnings[{code,item_id?}]` (e.g. `fewer_tips`, `reason_withheld_tone`, `short_session`) render as quiet notices.
*Transcript:* turns from `GET /sessions/{id}/transcript` with speaker label (`role`: Clinician/Client after confirm), timestamps (`start_ms`), highlight segments computed by a generic segmenter. Offsets from paudit/eaudit are **code points**, JS strings are UTF-16: convert via a code-point→UTF-16 index map (tested with emoji/accents). Rendered only as React text nodes (no `dangerouslySetInnerHTML`, no markdown/HTML parsing of any model or user text).

**R5 Dashboard.** `GET /dashboard`: 4 tiles — sessions rated, latest report (title, date, link), average global difference, share of items within one point; `–` when null (no rating) with "add your rating to see this" tooltip; recent reports list (title, date, version, status, runs) with **Run again** (`POST /sessions/{id}/runs`, `Idempotency-Key`, then session page); "New session" CTA; usage line from `GET /usage` ("3 of 20 runs today"); empty state for first-time users; over-cap disables Run again with `resets_at`.

**R6 Settings.** API key: `GET /api-key` metadata (prefix, created, last used); Create / Regenerate (confirm: old key stops working) / Revoke; secret shown **once** in a modal with copy button and "I've stored it" gate; held only in dialog state, never persisted. Link to API docs (`docs/reference/public-api.md` published copy) and a `curl` example with placeholder. Usage. Sign out. **Account deletion: not in v1** (SP04 defers the endpoint); settings text: per-session delete removes content; contact for account removal [OPEN: contact address].

**R7 Typed client + mock mode.** `openapi-typescript` generates `web/src/api/schema.d.ts` from `api/openapi.json` (copied/committed; `npm run gen:api`; CI fails if stale vs `api/openapi.json`); the report body is an opaque object in OpenAPI, so `json-schema-to-typescript` generates `web/src/api/report.d.ts` from `engines/evaluation/schemas/report.schema.json` in the same script and staleness check, and mock fixtures are validated against that schema in tests; `openapi-fetch` wrapper adds auth, base URL (`/v1`), `Idempotency-Key`, error-body parsing (`public-error-response`) and the 401 retry. TanStack Query for fetching/polling/mutations with `gcTime` short and in-memory only. Mock mode (`VITE_MOCK=1`): MSW handlers + typed fixtures (full state machine incl. gates, failure injection by title like the SP04 stub, report with N=1 and N=3, no-rating report, UTF-8 edge transcript), fake auth (`VITE_AUTH_MODE=fake` → `Bearer test:<uid>`, matching SP04 `AUTH_MODE=fake`). Live mode against SP04 `SERVICE_MODE=combined`: `npm run dev:live`.

**R8 Privacy/security/a11y.** No analytics, GA, trackers, error-reporting SDKs, or remote fonts (Inter self-hosted, copied from landing); only `firebase/auth` and first-party code. `localStorage`/`sessionStorage`/IndexedDB hold no app data (Firebase's own auth entry only); no PHI in URLs (ids only), `console` output, document titles, or error messages. Hosting headers: CSP (`default-src 'self'; script-src 'self'; connect-src 'self' https://identitytoolkit.googleapis.com https://securetoken.googleapis.com https://storage.googleapis.com; frame-src https://accounts.google.com https://*.firebaseapp.com; img-src 'self' data:; style-src 'self'; frame-ancestors 'none'`), `Referrer-Policy: no-referrer`, `X-Content-Type-Options: nosniff`, `Cache-Control: no-cache` on HTML, immutable on hashed assets, `private, no-cache` expected on `/v1` responses (API to set). A11y: semantic landmarks, labelled inputs, error summary with focus, focus moved to `h1` on route change, `aria-live` on status, keyboard-operable chips/gates, ≥4.5:1 contrast (landing tokens already AA), `prefers-reduced-motion`, 44 px targets, `eslint-plugin-jsx-a11y` + `vitest-axe` on every page. Mobile: single column ≥320 px, tables collapse to cards.

**R9 Tests.** Vitest + Testing Library + MSW: unit (code-point segmenter, difference chips, error mapping, token retry, upload progress with mocked XHR, polling/backoff with fake timers, rating form parity with the copied `rating.schema.json`), page tests per route, and **flow tests** (sign-up→verify→upload→speaker→rating→report; no-rating run; failure→run again; cap reached; delete session; API key once-only). Playwright: 3 smoke flows against `dev:mock` (signup/login, full session to report, mobile viewport) run in CI. `npm run typecheck`, `lint`, `test`, `build` are the gate.

## Architecture
```
Browser (app.onolys.com, Firebase Hosting: static dist/)
  ├─ firebase/auth ───────────────► Identity Platform (sign-in only, no PHI)
  ├─ /v1/**  (Hosting rewrite) ───► Cloud Run `api`  (Bearer ID token)
  └─ PUT signed URL (XHR) ────────► GCS audio bucket (CORS allow app origin; SP06)
```
```
web/
  index.html  vite.config.ts  firebase.json  package.json  .env.example
  src/{main.tsx, App.tsx, routes/, auth/, api/{schema.d.ts,client.ts,errors.ts,upload.ts,hooks/},
       features/{dashboard,session,report,settings}/, lib/{spans.ts,codepoints.ts,format.ts},
       protocol/miti-items.ts, styles/{tokens.css,app.css}, mocks/{handlers.ts,fixtures/}}
  e2e/  (Playwright)
```
Report/transcript data flow: `GET /reports/{rid}` (typed JSON; instances carry `turn_id`, `start`, `end` code-point offsets) + `GET /sessions/{id}/transcript` → `buildSegments(turn, instances)` → selected instance id in URL hash (`#i=…`, ids only) drives scroll + highlight. Item labels, reference levels and ordering come from the report JSON (`scorecard[].label`, `summaries[].reference`, `layout[]`), so the UI stays protocol-agnostic; only the rating-gate form uses the static `protocol/miti-items.ts` (labels, 1–5 anchors) with a parity test.

## Decisions
| # | Decision | Choice | Alternatives considered | Why |
|---|---|---|---|---|
| D1 | Hosting | Firebase Hosting site `onolys-app` (target `app`; staging `onolys-app-staging`, target `app-staging`; SP06 R11) serving `dist/`, `/v1/**` → Cloud Run `api` rewrite, SPA fallback last | Serve SPA from Cloud Run; separate `api.onolys.com` + CORS | Same stack/site pattern as landing; free CDN; same origin removes CORS and cookies-free preflights; `/__/auth/` works on custom domain. Rewrite limits (60 s, 32 MB bodies) are fine: API calls <1 s, uploads go direct to GCS. Resolves SP04 [OPEN] (see below) |
| D2 | Code sharing with `frontend/` | **Copy** small pieces (tokens, segmenter idea, a11y patterns); no workspace | npm workspace `packages/ui`; import across folders | `frontend/` contract/transport are eaudit-specific and admin will diverge; a root workspace is invasive (no root `package.json`) and slows SP07 rework; shared surface is ~200 lines. Revisit when a third consumer appears |
| D3 | Router/data | react-router + TanStack Query | Hand-rolled state (as `frontend/`); SWR | Polling, retries, caches and mutations are the job; `frontend/` has no routing needs |
| D4 | Client | openapi-typescript + openapi-fetch from committed `openapi.json` | orval/codegen hooks; hand-written | Types only, tiny runtime, no generated logic to review |
| D5 | Mock | MSW with typed fixtures in browser + vitest | Mock server process; no mock | Same handlers in dev, unit, e2e; unblocks SP05 before SP04 |
| D6 | Upload | XHR PUT, single object, auto-retry with fresh URL | fetch; tus/resumable chunks | Progress events; ≤100 MB single PUT is fine on home broadband; resumable adds complexity |
| D7 | Status | Polling 3 s, ETag, visibility-aware | SSE; Firestore listeners | Locked by brief/SP04 D4 |
| D8 | Token handling | SDK-managed token, per-request `getIdToken`, one forced refresh on 401 | Own storage of token; cookies/session cookies | Least custom code; no tokens in app storage |
| D9 | Account deletion | Out of v1; per-session delete only | Build delete-account | No endpoint (SP04 defers); legal owned by Tejit |
| D10 | Analytics/telemetry | None | GA, Sentry | PHI risk; v1 users are few and known |
| D11 | Transcript rendering | React text nodes + code-point offsets | `dangerouslySetInnerHTML` highlights | XSS-safe by construction |
| D12 | E2E | Vitest flow tests (required) + 3 Playwright smokes | Playwright only; none | Fast feedback + one real-browser check incl. mobile |

## Manual steps
- SP06 (Terraform) creates Hosting sites `onolys-app` (target `app`) and `onolys-app-staging` (target `app-staging`); Tejit adds the `app.onolys.com` DNS records from SP06's output; add `app.onolys.com` to Identity Platform authorised domains; add `https://app.onolys.com/__/auth/handler` to the Google OAuth client redirect URIs; customise verification/reset email templates (sender name, link domain).
- SP06: Cloud Run `api` must allow unauthenticated invocation (app-level auth) for the Hosting rewrite; GCS CORS on audio bucket (origin app host(s); methods PUT; headers `Content-Type`, `x-goog-content-length-range`).
- SP06: deploy workflow for `web/` (build with `VITE_FIREBASE_*` public config, `firebase deploy --only hosting:app-staging` on merge to `main`, `hosting:app` on prod promotion; SP06 R13).
- Tejit: provide a contact address for account-removal requests; sample real self-ratings for the rating-form check.

## Risks / Open Questions
- [RESOLVED: Hosting rewrite, same origin (SP04, SP05 D1, SP06 D4; (reconcile pass))] Residual staging check: verify that Hosting forwards `Authorization`, `If-None-Match`/`ETag` and does not cache `/v1` (API must send `Cache-Control: private, no-cache`); fallback is `api.onolys.com` + CORS (already allowed by SP04 R11) with a one-line base-URL change (`VITE_API_BASE`).
- [RESOLVED: SP04 adds `GET /sessions/{id}/transcript` (owner-scoped, access-logged) ((reconcile pass))] The rating-gate form keeps the static `protocol/miti-items.ts` (parity-tested against `rating.schema.json`); no protocol-metadata endpoint in v1.
- [RESOLVED: SP03 `report.schema.json` is the contract; UI types are generated from it ((reconcile pass))] Unknown `layout[]` sections are skipped, so later report additions do not break the UI.
- [RESOLVED: API accepts `n_runs` (1–5, default 1) and allowlisted `preset`; `GET /v1/presets` lists them; web shows both under Advanced ((reconcile pass))]
- [OPEN] Custom email-action handler (verify/reset links land on Firebase default handler then continue to `/verify-email`); default accepted for v1.
- [OPEN] CSP `frame-src`/`connect-src` hosts for Identity Platform popup: confirm in staging; `style-src 'self'` may need hashes if a lib injects styles.
- [RESOLVED: copy] Share code with `frontend/` (D2).
- [RESOLVED: no] Google Analytics / third-party scripts in app.
- [DEFERRED] Audio playback at timestamp, resumable chunked upload, delete account, auto-expiry setting UI, i18n, dark mode.
- Risk: report offsets drifting from transcript text if SP04 stores transcript differently from engine input; mitigation: segmenter verifies `turn.text.slice` equals `quote` in dev and degrades to an unhighlighted quote list in prod.
- Risk: iOS Safari large-file `PUT` and Google popup quirks; mitigate with mobile Playwright smoke and redirect fallback.

## Acceptance Criteria
1. `npm run typecheck && lint && test && build` pass in `web/` with no network; `gen:api` produces no diff against committed `api/openapi.json`.
2. In mock mode, full flow works: sign-up → verify → create session (100 MB fixture shows progress, cancel works) → speaker confirm (3 lines each) → rating confirm (editable) → `report_ready` → report v1; Run again creates v2; switcher shows both; delete removes session.
3. Report shows scorecard with difference chips (text + tone), disagreement blocks with evidence, clickable instances that scroll/highlight in transcript, "reference levels, not pass marks", tips, method note; N=3 fixture shows mean + range; no-rating fixture shows "–" in dashboard tiles and Onolys-only scorecard.
4. Code-point offsets highlight correctly on a transcript containing emoji and combining accents; no `dangerouslySetInnerHTML` in `web/src` (lint rule).
5. Token handling: expired token → one forced refresh then retry; second 401 signs out; unverified user cannot reach `/`.
6. Failure states: each mapped error code renders its message + reference id; `validate`/`transcribe` failure offers new upload, later failure offers Run again; cap reached disables Run again with reset time.
7. Settings: API key secret visible once, absent after dismiss/reload, never in storage or logs (test inspects `localStorage`, `sessionStorage`, console spy).
8. No requests to hosts outside the CSP list in Playwright network log; no analytics code; axe finds no serious violations on any route at 375 px and 1280 px.
9. Against SP04 `SERVICE_MODE=combined` with fake auth, the Playwright full-session flow passes (run once SP04 lands).
10. `web/firebase.json` contains the `/v1/**` rewrite before the SPA fallback, CSP/headers above, and a staging target; deploys to staging verified by SP06.
