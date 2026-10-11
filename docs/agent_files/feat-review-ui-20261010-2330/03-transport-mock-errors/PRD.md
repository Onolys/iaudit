---
status: draft
summary: Upload-to-validated-audit pipeline (file parse, request validation, POST with fixed timeout/cancel/retry or mock lookup by request_id, response validation), error screens per case (non-2xx bodies validated against error-response.schema.json), and the partial/warnings banner.
date: 2026-10-10
---
# PRD: 03 Transport, mock mode, errors

Repo/branch: iaudit / `feat/review-ui` · Depends on: 01-frontend-scaffold, 02-contract-core · Owns: `frontend/src/transport/` (loader, client, mock registry, error types, `LoadingView`, `ErrorScreen`, `WarningsBanner`, colocated tests) + a "Mock mode" section appended to `frontend/README.md`

## TL;DR
Everything between "reviewer picks a file" and "validated audit in hand": read and validate the request file, send it (or look up a bundled mock), validate the reply, and turn every failure into one typed `LoadError` with its own plain screen. SP04 consumes a single `useAuditLoader()` state machine; it never touches fetch or Ajv.

## Problem
The contract defines one synchronous call and forbids rendering a half-valid audit. Failures are many (bad file, network, timeout, non-2xx, bad body, wrong echo) and each needs distinct, honest wording. The backend does not exist and its path/CORS are unagreed; mock mode must unblock UI work and stay extensible as SP06 adds fixtures. Non-2xx bodies follow `docs/contracts/error-response.schema.json`.

## Goals / Non-Goals
**Goals**
- One pipeline, one result type, one error union; every error has a screen with the locked copy.
- Cancel, timeout, retry, and safe handling of re-upload during an in-flight call.
- Mock mode that runs the same validation path as the real one.
- Warnings banner for `status: partial` / `warnings[]`.

**Non-Goals**
- Header/upload button UI, app state, panes, "Not processed" badge (SP04). Span math and schema logic (SP02).
- Auth, cookies, retries with backoff, streaming, caching, persistence of uploads or responses.
- Drag-and-drop upload, multi-file upload, upload size cap, configurable timeout. Request/response contract changes.

## Requirements
**R1 Pipeline** (pure async `runAudit`, DOM-free; fetch injectable):
1. Read: `file.text()` (strip leading BOM) -> empty/whitespace -> `invalid_request_file/empty`; `JSON.parse` failure -> `not_json` (engine message); then SP02 `validateRequest` -> `schema` with `issues[]`. Nothing is sent on any of these.
2. If not mock and `VITE_AUDIT_URL` is null -> `config_missing`. Nothing sent.
3. Mock: R4. Real: R2.
4. Body text -> `JSON.parse` (fail -> `invalid_response/not_json`; empty -> `empty`) -> SP02 `validateResponse(raw, request)` -> `analyzeResponse(request, response)`.
5. Result: `{ ok: true, request, response, analysis, source: 'service' | 'mock' }`. `analysis` is SP02's `ResponseAnalysis` (per-claim span checks, counts, ordering); it replaces the `spanIssues` field named in the initiative brief.

**R2 Client**: `POST` to `VITE_AUDIT_URL`, headers `Content-Type: application/json`, `Accept: application/json`, `credentials: 'omit'`, body `JSON.stringify(request)` of the validated object. One `AbortController` per attempt; a timer (fixed constant `TIMEOUT_MS = 120_000`, no env var) covers headers **and** body read. Abort reason recorded before aborting so `timeout` and `cancelled` are distinguishable. Response body is read with `res.text()` then parsed (so non-JSON is diagnosable). Non-2xx: see R5.

**R3 Error taxonomy** (`LoadError`, discriminated by `kind`; screens render exact title, then detail, then actions):
| kind | Title (exact) | Detail | Actions |
|---|---|---|---|
| `invalid_request_file` (`empty` / `not_json` / `schema`) | Invalid request file | issues list (`path` + `message`), first 50 then "and N more" | Choose another file |
| `config_missing` | Audit service not configured | `VITE_AUDIT_URL` is not set; mock mode is off | Choose another file |
| `mock_no_match` | No mock audit for this request | the request's `request_id` (or "none") | Choose another file |
| `network` | Couldn't reach the audit service. | configured URL; hint "service down, wrong URL, or CORS" (fetch cannot tell these apart) | Retry |
| `timeout` | Request timed out | after N s | Retry |
| `cancelled` | Cancelled. | - | Retry |
| `http_4xx` | Request rejected (status) | `error.message` if the body validates (R5) | Choose another file; Retry only for 408/429 |
| `http_5xx` (also any other non-2xx) | Audit service error (status). | `error.message` if the body validates (R5) | Retry |
| `invalid_response` (`empty` / `not_json` / `not_object` / `wrong_version` / `schema` / `duplicate_claim_id`) | Invalid audit response | issues, or reason sentence for version/dup-id | Choose another file |
| `request_id_mismatch` | Response doesn't match this request. | expected vs received | Choose another file |
Screens use `role="alert"`, plain text only (server text is never rendered as HTML). No audit data is shown on any error.

**R4 Mock mode** (`VITE_MOCK === "true"`): no network. A registry built from a **lazy** `import.meta.glob('../../../docs/contracts/examples/*.json')` (relative path from `frontend/src/transport/mock/`; no alias). Lazy so fixtures are separate chunks never fetched in a real-service session.
- **Naming** (SP06 follows): a pair is `<name>.request.json` + `<name>.response.json`; the existing `request.json` / `response.json` is the pair `default`. Parse with `^(?:(.+)\.)?(request|response)\.json$`. Other files in the folder (for example `error.json`) are ignored.
- **Match**: by `request_id` exact. No `request_id` or no match -> `mock_no_match` ("No mock audit for this request"). Id match does not compare content.
- Simulated latency 250 ms, abortable. The fixture is returned as a body string and passes through R1.4 like a real reply.
- One unit test: every request has a response and vice versa, and `request_id`s are unique.

**R5 Non-2xx bodies**: parse the body as JSON and validate against `error-response.schema.json` (compiled with Ajv alongside the other schemas; SP02/SP01 own the Ajv setup). If valid, show `error.message` (plain text). If not (empty, HTML, other JSON, parse failure), show no body text, only the status title. Never render an audit from an error body.

**R6 Loader state machine** (`useAuditLoader()`, thin React wrapper over R1):
```ts
type LoaderState =
  | { status: 'idle' }
  | { status: 'loading'; fileName: string; requestId?: string }
  | { status: 'ok'; fileName: string; result: LoadResult }
  | { status: 'error'; fileName?: string; error: LoadError };
// returns { state, loadFile(file), retry(), cancel(), reset() }
```
- Each `loadFile`/`retry` gets a monotonically increasing generation id and aborts the previous attempt. Any completion with a stale generation is dropped (no state write). Cancel/unmount aborts.
- `retry()` re-runs from the stored **validated request** (no file re-read); it is a no-op unless the last state is a retryable error.
- Starting a load sets `loading` immediately, so the previous audit disappears (see SP04 D8).

**R7 Components**: `LoadingView` ("Auditing...", request_id if known, Cancel button), `ErrorScreen({error, onRetry?, onChooseFile})` (Retry only when the taxonomy allows), `WarningsBanner({response})`.
- Banner renders iff `status === 'partial'` or `warnings.length > 0`. Heading "Audit completed with warnings" (partial: "Audit is partial: some sections were not processed"). Lists service warnings verbatim (code label + `message`; `section_index` as "Section N", `claim_id` as id). Never dismissible. Wording stays "potential concern" style; no allegation language. Claims with out-of-range spans are flagged per claim by SP04/05 from `analysis`, not here.

**R8 Privacy**: the request holds sensitive interview text. It goes only to the configured URL; never logged, never stored (no localStorage), no third-party calls.

## Architecture
```
File -> readUpload -> validateRequest(SP02) --fail--> invalid_request_file
     -> mock? registry.lookup : client.post(url, req, signal)
     -> body text -> JSON.parse -> validateResponse(SP02) -> analyzeResponse(SP02)
     -> LoadResult | LoadError
transport/  runAudit.ts  client.ts  mock/registry.ts  errors.ts  useAuditLoader.ts
            LoadingView.tsx  ErrorScreen.tsx  WarningsBanner.tsx
```
Assumes from SP02: `validateRequest`, `validateResponse` (returns `ResponseError` with kinds `not_object | wrong_version | schema | request_id_mismatch | duplicate_claim_id`), `analyzeResponse`, `ValidationIssue`. Provides to SP04: `useAuditLoader`, `LoadResult`, `LoadError`, the three components. `getConfig()` from SP01.

## Decisions
| # | Decision | Choice | Alternatives considered | Why |
|---|---|---|---|---|
| 1 | Mock source | Lazy `import.meta.glob` (relative path) of `docs/contracts/examples/` | Eager glob; copy fixtures into `frontend/`; mock server | No copies (locked); lazy keeps fixtures out of real sessions |
| 2 | Pair naming | `<name>.request.json` / `.response.json`; bare = `default` | Folder per pair; manifest file | Works with today's files; no manifest to forget |
| 3 | Mock matching | `request_id` only | Deep-equal; content hash; first pair always | Simplest; "first pair" would show wrong audit silently |
| 4 | No match | Error screen | Fall back to default pair | A mismatched audit looks real; mission forbids misleading output |
| 5 | Mock passes validation | Same path as real | Skip validation | Fixtures get tested; same error screens reachable |
| 6 | Timeout | Fixed 120 s constant | Env var; 30 s, 60 s | Long synchronous call; no config needed for MVP |
| 7 | Re-upload in flight | Abort previous + generation guard | Disable upload while loading; queue | Never shows a stale audit for a different file |
| 8 | Retry source | Stored validated request | Re-read file | File handle may be gone; request already validated |
| 9 | 4xx retry | None, except 408/429 | Always/never | Brief says no retry for 4xx; those two are transient by definition |
| 10 | Non-2xx other than 4xx | Treated as 5xx screen | Separate screen | Rare (unfollowed 3xx); same user action |
| 11 | Warnings source | Service warnings verbatim | Also viewer-found line | Out-of-range claims are badged per claim; banner stays simple |
| 12 | `Content-Type` | `application/json` | `text/plain` to dodge preflight | Honest typing; CORS deferred |
| 13 | `analysis` in result | Return SP02 `ResponseAnalysis` | Raw `spanIssues` list | SP04 needs counts/order/checks; computed once |
| 14 | Error body | Validate against `error-response.schema.json`; generic text otherwise | Heuristic field sniffing | Agreed contract; no guessing |

## Manual steps
- Before real-service integration: agree endpoint path and CORS (incl. `OPTIONS` preflight) with the backend team. Mock mode covers development until then.

## Risks / Open Questions
- [DEFERRED] O-03-1 Endpoint path and CORS policy; backend does not exist [verified: no backend code in repo]. Mock mode covers the MVP.
- [RESOLVED: fixed 120 s constant, no env var] O-03-2 Timeout.
- [RESOLVED: 4xx/5xx bodies validated against `error-response.schema.json`; show `error.message` if valid, else generic text] O-03-3 Error-body shape.
- [RESOLVED: relative path in `import.meta.glob`, no alias] O-03-4 Glob and `@contracts` alias.
- [RESOLVED: handled by SP06] O-03-5 Contract README wording for extra fixtures.
- [RESOLVED: generation guard + abort] Re-upload during in-flight request.
- [RESOLVED: no-match -> error] Mock without a matching pair.
- [DEFERRED] Drag-and-drop upload; upload size cap.

## Acceptance Criteria
- Each R3 row has a test (fake fetch / fake timers) asserting `kind` and the exact screen title; no test passes by rendering an audit on failure.
- Invalid request file: `fetch` is never called (spy count 0), for empty, non-JSON, and schema-failing files; issues show path + message.
- Timeout fires at 120 s (fake timers) and yields `timeout`; Cancel yields `cancelled`; both abort the fetch signal; Retry issues a new POST with the same body.
- Upload B while A is in flight: A's late response never reaches state; final state reflects B only.
- POST uses `Content-Type: application/json`, `credentials: 'omit'`, body deep-equals the uploaded request.
- Mock mode with `examples/request.json`: no `fetch` call, returns `ok` with `source: 'mock'`; a request with an unknown `request_id` returns `mock_no_match`.
- Response with version `2.0.0`, extra field, or `request_id` mismatch yields `invalid_response` / `request_id_mismatch`, never `ok`.
- Banner: `partial` and a `warnings[]`-only response both render it; a clean `complete` response does not.
- 400 with `examples/error.json` shows its `error.message`; 500 with an HTML body shows only the status title, no body text.
