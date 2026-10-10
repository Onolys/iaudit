---
status: draft
summary: Upload-to-validated-audit pipeline (file parse, request validation, POST with timeout/cancel/retry or mock lookup, response validation), full error taxonomy with screens, and the partial/warnings banner.
date: 2026-10-10
---
# PRD: 03 Transport, mock mode, errors

Repo/branch: iaudit / `feat/review-ui` · Depends on: 01-frontend-scaffold, 02-contract-core · Owns: `frontend/src/transport/` (loader, client, mock registry, error types, `LoadingView`, `ErrorScreen`, `WarningsBanner`, colocated tests) + a "Mock mode" section appended to `frontend/README.md`

## TL;DR
Everything between "reviewer picks a file" and "validated audit in hand": read and validate the request file, send it (or look up a bundled mock), validate the reply, and turn every failure into one typed `LoadError` with its own plain screen. SP04 consumes a single `useAuditLoader()` state machine; it never touches fetch or Ajv.

## Problem
The contract defines one synchronous call and forbids rendering a half-valid audit. Failures are many (bad file, CORS, timeout, 4xx, 5xx, bad body, wrong echo) and each needs distinct, honest wording. The backend does not exist, so path, CORS, timeout and error-body shape are unagreed; mock mode must unblock UI work and stay extensible as SP06 adds fixtures.

## Goals / Non-Goals
**Goals**
- One pipeline, one result type, one error union; every error has a screen with the locked copy.
- Cancel, timeout, retry, and safe handling of re-upload during an in-flight call.
- Mock mode that runs the same validation path as the real one.
- Warnings banner for `status: partial` / `warnings[]`.

**Non-Goals**
- Header/upload button UI, app state, panes, "Not processed" badge (SP04). Span math and schema logic (SP02).
- Auth, cookies, retries with backoff, streaming, caching, persistence of uploads or responses.
- Drag-and-drop upload, multi-file upload. Contract changes.

## Requirements
**R1 Pipeline** (pure async `runAudit`, DOM-free; fetch injectable):
1. Read: `file.text()` (strip leading BOM) -> empty/whitespace -> `invalid_request_file/empty`; `JSON.parse` failure -> `not_json` (engine message); then SP02 `validateRequest` -> `schema` with `issues[]`. Nothing is sent on any of these.
2. If not mock and `VITE_AUDIT_URL` is null -> `config_missing`. Nothing sent.
3. Mock: R4. Real: R2.
4. Body text -> `JSON.parse` (fail -> `invalid_response/not_json`; empty -> `empty`) -> SP02 `validateResponse(raw, request)` -> `analyzeResponse(request, response)`.
5. Result: `{ ok: true, request, response, analysis, source: 'service' | 'mock' }`. `analysis` is SP02's `ResponseAnalysis` (per-claim span checks, counts, ordering); it replaces the `spanIssues` field named in the initiative brief.

**R2 Client**: `POST` to `VITE_AUDIT_URL`, headers `Content-Type: application/json`, `Accept: application/json`, `credentials: 'omit'`, body `JSON.stringify(request)` of the validated object. One `AbortController` per attempt; a timer (default **120 000 ms**, `DEFAULT_TIMEOUT_MS`, overridable by argument for tests) covers headers **and** body read. Abort reason recorded before aborting so `timeout` and `cancelled` are distinguishable. Response body is read with `res.text()` then parsed (so non-JSON is diagnosable).

**R3 Error taxonomy** (`LoadError`, discriminated by `kind`; screens render exact title, then detail, then actions):
| kind | Title (exact) | Detail | Actions |
|---|---|---|---|
| `invalid_request_file` (`empty` / `not_json` / `schema`) | Invalid request file | issues list (`path` + `message`), first 50 then "and N more" | Choose another file |
| `config_missing` | Audit service not configured | `VITE_AUDIT_URL` is not set; mock mode is off | Choose another file |
| `mock_no_match` | No mock audit for this request | the request's `request_id` (or "none") and the available mock ids | Choose another file |
| `network` | Couldn't reach the audit service. | configured URL; hint "service down, wrong URL, or CORS" (fetch cannot tell these apart) | Retry |
| `timeout` | Request timed out | after N s | Retry |
| `cancelled` | Cancelled. | - | Retry |
| `http_4xx` | Request rejected (status) | server message if extractable (R5) | Choose another file; Retry only for 408/429 |
| `http_5xx` (also any other non-2xx) | Audit service error (status). | - | Retry |
| `invalid_response` (`empty` / `not_json` / `not_object` / `wrong_version` / `schema` / `duplicate_claim_id`) | Invalid audit response | issues, or reason sentence for version/dup-id | Choose another file |
| `request_id_mismatch` | Response doesn't match this request. | expected vs received | Choose another file |
Screens use `role="alert"`, plain text only (server text is never rendered as HTML). No audit data is shown on any error.

**R4 Mock mode** (`VITE_MOCK === "true"`): no network. A registry built from a **lazy** `import.meta.glob('@contracts/examples/*.json')` (alias in glob patterns is supported by Vite [from Vite docs, not run]; fallback is the relative path `../../../docs/contracts/examples/*.json`). Lazy so the fixtures are separate chunks never fetched in a real-service session.
- **Naming convention** (SP06 must follow): a pair is `<name>.request.json` + `<name>.response.json`; the existing `request.json` / `response.json` is the pair named `default`. Registry parses names with `^(?:(.+)\.)?(request|response)\.json$`.
- **Match**: by `request_id` exact. A request without `request_id` matches only a bundled request that is deep-equal to it. No match -> `mock_no_match`. Id match does not compare content (SP02's bounds checks guard a stale fixture).
- Simulated latency 250 ms, abortable, so loading/cancel behave like production. The fixture is `structuredClone`d and returned as a body string, so it passes through R1.4 exactly as a real reply would; a fixture that is not a valid response yields the same `invalid_response` screen.
- Registry invariants (enforced by a unit test, ignored at runtime except a dev `console.warn`): every request has exactly one response and vice versa; every request validates; every response validates against its own request; `request_id`s are unique across pairs.

**R5 4xx body message** (shape unagreed): parse body as JSON and take the first string found at `message`, `detail`, `error`, `error.message`, `errors[0].message`; else, if the body is plain text under 500 chars, use it; else none. Truncate to 500 chars. Heuristic, easy to narrow once the backend defines it.

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

**R7 Components**: `LoadingView` ("Auditing...", request_id if known, Cancel button), `ErrorScreen({error, onRetry?, onChooseFile})` (Retry only when the taxonomy allows), `WarningsBanner({request, response, analysis})`.
- Banner renders iff `status === 'partial'` or `warnings.length > 0` or `analysis` flags a claim the service did not warn about. Heading "Audit completed with warnings" (partial: "Audit is partial: some sections were not processed"). Lists service warnings verbatim (code label + `message`; `section_index` shown as the section's label or "Section N", `claim_id` as id), then a separate line "Found by this viewer: N claim(s) have positions outside the supplied text" with ids. Max-height with internal scroll; never dismissible (warnings must stay visible). Wording stays "potential concern" style; no allegation language.

**R8 Privacy**: the request holds sensitive interview text. It goes only to the configured URL; never logged (no `console.*` of bodies or issues' values), never stored (no localStorage), no third-party calls.

## Architecture
```
File -> readUpload -> validateRequest(SP02) --fail--> invalid_request_file
     -> mock? registry.lookup : client.post(url, req, signal, timeout)
     -> body text -> JSON.parse -> validateResponse(SP02) -> analyzeResponse(SP02)
     -> LoadResult | LoadError
transport/  runAudit.ts  client.ts  mock/registry.ts  errors.ts  useAuditLoader.ts
            LoadingView.tsx  ErrorScreen.tsx  WarningsBanner.tsx
```
Assumes from SP02: `validateRequest`, `validateResponse` (returns `ResponseError` with kinds `not_object | wrong_version | schema | request_id_mismatch | duplicate_claim_id`), `analyzeResponse`, `ValidationIssue`. Provides to SP04: `useAuditLoader`, `LoadResult`, `LoadError`, the three components. `getConfig()` from SP01.

## Decisions
| # | Decision | Choice | Alternatives considered | Why |
|---|---|---|---|---|
| 1 | Mock source | Lazy `import.meta.glob` of `docs/contracts/examples/` | Eager glob; copy fixtures into `frontend/`; mock server | No copies (locked); lazy keeps fixtures out of real sessions |
| 2 | Pair naming | `<name>.request.json` / `.response.json`; bare = `default` | Folder per pair; manifest file | Works with today's files; no manifest to forget |
| 3 | Mock matching | `request_id`, else deep-equal | Content hash; first pair always | Contract echoes ids; "first pair" would show wrong audit silently |
| 4 | No match | Error screen listing available ids | Fall back to default pair | A mismatched audit looks real; mission forbids misleading output |
| 5 | Mock passes validation | Same path as real | Skip validation | Fixtures get tested; same error screens reachable |
| 6 | Timeout default | 120 s | 30 s, 60 s, none | Synchronous LLM-style call over a long assessment; tune after measuring [OPEN] |
| 7 | Re-upload in flight | Abort previous + generation guard | Disable upload while loading; queue | Never shows a stale audit for a different file |
| 8 | Retry source | Stored validated request | Re-read file | File handle may be gone; request already validated |
| 9 | 4xx retry | None, except 408/429 | Always/never | Brief says no retry for 4xx; those two are transient by definition |
| 10 | Non-2xx other than 4xx | Treated as 5xx screen | Separate screen | Rare (unfollowed 3xx); same user action |
| 11 | Warnings source | Service warnings verbatim + viewer-found line | Service only; viewer only | SP02 flag is authoritative for rendering; backend may omit its own warning |
| 12 | `Content-Type` | `application/json` (preflighted) | `text/plain` to dodge preflight | Honest typing; backend must allow OPTIONS [OPEN] |
| 13 | `analysis` in result | Return SP02 `ResponseAnalysis` | Raw `spanIssues` list | SP04 needs counts/order/checks; computed once |

## Manual steps
- Agree endpoint path, CORS (incl. `OPTIONS` preflight, `Content-Type`), and error-body shape with the backend team before real-service integration. Mock mode covers development until then.

## Risks / Open Questions
- [OPEN] Endpoint path and CORS policy not agreed; backend does not exist [verified: no backend code in repo].
- [OPEN] Timeout 120 s is a guess; measure on one real-length case. A `VITE_AUDIT_TIMEOUT_MS` var would touch SP01's env typing; deferred until needed.
- [OPEN] 4xx/5xx error-body shape unknown; R5 is a heuristic.
- [OPEN] Does `import.meta.glob` accept the `@contracts` alias in this setup? Verify first at implementation; relative fallback is defined.
- [OPEN] Extra fixtures in `docs/contracts/examples/` vs the README's "one worked example": adding files is not a schema change, but the contract README wording may need a note (SP06; we do not edit `docs/contracts/` here).
- [RESOLVED: generation guard + abort] Re-upload during in-flight request.
- [RESOLVED: no-match -> error] Mock without a matching pair.
- [DEFERRED] Drag-and-drop upload; upload size cap (very large files are read fully into memory).

## Acceptance Criteria
- Each R3 row has a test (fake fetch / fake timers) asserting `kind` and the exact screen title; no test passes by rendering an audit on failure.
- Invalid request file: `fetch` is never called (spy count 0), for empty, non-JSON, and schema-failing files; issues show path + message.
- Timeout fires at the configured ms and yields `timeout`; Cancel yields `cancelled`; both abort the fetch signal; Retry afterwards issues a new POST with the same body.
- Upload B while A is in flight: A's late response never reaches state; final state reflects B only.
- POST uses `Content-Type: application/json`, `credentials: 'omit'`, body deep-equals the uploaded request.
- Mock mode with `examples/request.json`: no `fetch` call, returns `ok` with `source: 'mock'`; a request with an unknown `request_id` returns `mock_no_match` listing `example-001`.
- Registry invariants test passes today and fails if a `*.request.json` has no response, or ids collide.
- Response with version `2.0.0`, extra field, or `request_id` mismatch yields `invalid_response` / `request_id_mismatch`, never `ok`.
- Banner: `partial` + `section_not_processed` and a `warnings[]`-only response both render the banner; a clean `complete` response does not.
- 4xx with `{"message":"bad"}` shows "bad"; with HTML body shows no body text and no HTML injection.
- No `console.*` output containing request/response content (spy test).
