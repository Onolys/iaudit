---
status: draft
summary: Four tasks: error taxonomy and client, mock registry and runAudit pipeline, loader state machine, screens and warnings banner.
date: 2026-10-10
---
# Tasks: 03 Transport, mock mode, errors

Source of truth: docs/agent_files/feat-review-ui-20261010-2330/03-transport-mock-errors/PRD.md. Takes an uploaded file to a validated audit (or a typed `LoadError`) via real POST or a bundled mock, and provides the loader hook and error/loading/warning components to SP04.

| # | Task | Depends on | Status |
|---|---|---|---|
| 1 | Error types and HTTP client | 02/T1 | done |
| 2 | Mock registry and runAudit pipeline | 1, 02/T4 | done |
| 3 | useAuditLoader state machine | 2 | done |
| 4 | LoadingView, ErrorScreen, WarningsBanner | 1, 3 | done |

## Task 1 — Error types and HTTP client
What it is / what it means: The `LoadError` union and the fetch layer (R2, R3 taxonomy, R5, R8; Decisions 6, 9, 10, 12, 14).
What changes at a high level: Define `LoadError` and `LoadResult` per the R3 kinds. Build an injectable-fetch POST client: JSON headers, `credentials: 'omit'`, one `AbortController` per attempt, fixed 120 s `TIMEOUT_MS` covering headers and body, abort reason recorded so `timeout` and `cancelled` differ, body read via `text()`. Map network failures and non-2xx statuses (4xx, 5xx, others as 5xx); validate non-2xx bodies against `error-response.schema.json` (compiled with Ajv) and keep `error.message` only if valid. Nothing is logged or stored.
Done when: fake-fetch and fake-timer tests assert kind per case, timeout at 120 s, cancel, abort of the signal, and that an HTML 500 body yields no body text while `examples/error.json` on a 400 yields its message.

## Task 2 — Mock registry and runAudit pipeline
What it is / what it means: The DOM-free pipeline from file to `LoadResult`, with mock mode on the same validation path (R1, R4; Decisions 1-5, 8).
What changes at a high level: Add a lazy `import.meta.glob` registry (relative path to `docs/contracts/examples/`, no alias) parsing `<name>.request|response.json`, bare files as `default`, other files ignored, matched by exact `request_id`, with 250 ms abortable latency and no-match giving `mock_no_match`. Implement `runAudit`: read the file (strip BOM; empty, not-JSON and schema errors become `invalid_request_file`), `config_missing` check, mock or POST, then parse, `validateResponse` and `analyzeResponse`. Invalid requests never reach fetch.
Done when: tests show fetch spy count 0 for invalid files and in mock mode, `ok` with `source: 'mock'` for `examples/request.json`, `mock_no_match` for an unknown id, `invalid_response`/`request_id_mismatch` for version 2.0.0, extra field and id mismatch, and a registry test that pairs are complete with unique ids.

## Task 3 — useAuditLoader state machine
What it is / what it means: The thin React wrapper SP04 consumes (R6; Decisions 7, 8).
What changes at a high level: Implement `useAuditLoader()` returning `{ state, loadFile, retry, cancel, reset }` over the idle/loading/ok/error states. Each load or retry takes an increasing generation id and aborts the previous attempt; stale completions are dropped. `retry` reuses the stored validated request and is a no-op unless the last state is a retryable error. Cancel and unmount abort. Loading is set immediately.
Done when: tests show uploading B while A is in flight leaves only B's result, retry sends a new POST with an identical body, cancel yields `cancelled`, and the POST body deep-equals the uploaded request.

## Task 4 — LoadingView, ErrorScreen, WarningsBanner
What it is / what it means: The user-visible screens with the locked copy (R3 table, R7; Decision 11).
What changes at a high level: `LoadingView` shows "Auditing...", the request_id if known, and Cancel. `ErrorScreen` renders the exact title, detail (issues capped at 50 plus "and N more") and actions per kind, with Retry only where the taxonomy allows (network, timeout, cancelled, 5xx, 408/429), `role="alert"`, plain text only. `WarningsBanner` renders iff `status === 'partial'` or warnings exist, with the specified headings, verbatim warnings, never dismissible. Append the "Mock mode" section to `frontend/README.md`.
Done when: component tests (jsdom) assert the exact title for every R3 row, no audit data on errors, banner shown for partial and for warnings-only, and absent for a clean complete response.

## Manual steps (human)
Before real-service integration, agree the endpoint path and CORS (including OPTIONS preflight) with the backend team. Mock mode covers development until then.
