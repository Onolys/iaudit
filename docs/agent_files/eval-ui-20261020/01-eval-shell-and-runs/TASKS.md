---
status: in-progress
summary: Ten tasks: Vite proxy and config, typed evalApi client, schema-validated fixtures, usePolling, EvalApp shell, Audit/Eval toggle, RunPanel form, RunPanel run lifecycle, RunsList, docs.
date: 2026-10-20
---
# Tasks: 01 Eval shell and runs (D1)

Source of truth: docs/agent_files/eval-ui-20261020/01-eval-shell-and-runs/PRD.md. Adds the Audit | Eval switch and the Eval tab's Run panel and Runs list on top of B4's eval API. All verification is fake-fetch, fake-timer or offline stub-server; no live LLM calls and no real-browser or live-server smoke.

| # | Task | Depends on | Status |
|---|---|---|---|
| 1 | Proxy, config and schema alias | none | done |
| 2 | Eval types and evalApi client | 1 | done |
| 3 | Fixtures and schema validation | 2 | done |
| 4 | usePolling hook | none | done |
| 5 | EvalApp shell and view slot | 2, 4 | in-progress |
| 6 | Audit / Eval toggle | 5 | todo |
| 7 | RunPanel form and estimate | 3, 5 | todo |
| 8 | RunPanel run lifecycle | 4, 7 | todo |
| 9 | RunsList | 3, 5, 8 | todo |
| 10 | Eval UI reference docs | 6, 9 | todo |

## Task 1 — Proxy, config and schema alias
What it is / what it means: Dev-server plumbing so the frontend reaches the eval server and tests can import B4's schema (PRD R7; Decision 7; AC 10).
What changes at a high level: Add the `/eval-api` proxy to dev and preview servers, targeting the eval port from `IAUDIT_EVAL_PORT` (default 8100), stripping the prefix, keeping the original Host. Add optional `VITE_EVAL_API_BASE` (default `/eval-api`) to config, env typings and `.env.example`; `getConfig` stays non-throwing. Add the `@eval-api` alias to `eval/api` with a matching `server.fs.allow` entry. Add an offline test that starts a stub HTTP server and checks `/eval-api/health` through the proxy config reaches it with the prefix removed.
Done when: config tests cover default and override; the alias resolves the schema in a test; the stub-server proxy test passes; existing config tests stay green.

## Task 2 — Eval types and evalApi client
What it is / what it means: The single typed, never-throwing client for all eval server calls (PRD R2; Decisions 3, 4).
What changes at a high level: Add `evalTypes` hand-mirroring B4's schema shapes, `EvalError` and `ApiCode`, and a `createEvalApi` factory with injected fetch and base URL. Implement all sixteen methods D1 and D2 need, returning `Result` from `contract`, with `credentials: omit`, abort signal support, 10 s default and 30 s POST timeouts, and error-body parsing. Map network failure and 502 to unreachable, plus timeout, cancelled, api (every code) and bad_body. Only the first method set is used by D1; the rest are tested for path, method and body.
Done when: `evalApi.test` covers path/method/body per method, each error kind, each ApiCode, non-JSON bodies, and that nothing throws.

## Task 3 — Fixtures and schema validation
What it is / what it means: Canned API responses shared with D2, proven against B4's committed schema so drift fails CI (PRD R9 fixtures row; Decision 4; AC 9).
What changes at a high level: Add JSON fixtures under the eval folder covering health, datasets and dataset detail, estimate (known and unknown basis), download states, run progress, runs list with every state, and error bodies. Add a test that validates each fixture with Ajv against the matching `$defs` entry via the schema's route table, imported through `@eval-api`.
Done when: every fixture validates; a deliberately malformed fixture would fail the test; later tasks reuse these fixtures.

## Task 4 — usePolling hook
What it is / what it means: The shared sequential poller used for run and download progress (PRD R3; Decision 5; AC 8).
What changes at a high level: Add `usePolling` returning data, error, misses and stale. First call immediate, next scheduled only after the previous resolves, stops on terminal data or disabled, aborts in-flight work and clears the timer on unmount. A failed poll keeps last data and increments misses; success resets; a generation counter drops late results.
Done when: fake-timer tests prove 1 s cadence, no overlap, stop on terminal, unmount aborts and stops fetching, and three misses flag then recover.

## Task 5 — EvalApp shell and view slot
What it is / what it means: The Eval tab container and view state D2 will plug into (PRD R4, R8 server-down row; AC 3).
What changes at a high level: Add `EvalApp` owning one `evalApi` (overridable by prop for tests) and the four-way view state (list, run, item, compare). Render only the list view for real; render a `ViewSlot` stub ("Run detail — coming in D2") for the other three so navigation is wired. On mount call health; failure shows a "not reachable" banner with Retry, leaving Audit unaffected. Include eval styles.
Done when: tests show healthy render, banner plus Retry recovery, and that setting each view renders the slot.

## Task 6 — Audit / Eval toggle
What it is / what it means: The top-level switch, with Audit behavior unchanged (PRD R1; Decisions 1, 2; AC 2).
What changes at a high level: Move the current `App` body into `AuditApp` in the same file, keeping `deps`. New thin `App` holds `"audit" | "eval"` state with two `aria-pressed` buttons above the content and conditionally renders (unmounts) either side. Header, ReviewShell, transport and contract untouched.
Done when: existing `App.test` passes unchanged; extended tests show the toggle swaps views, Audit idle prompt is intact, returning to Audit is fresh, and toggling to Audit mid-run causes zero further fetches.

## Task 7 — RunPanel form and estimate
What it is / what it means: The pre-run inputs and cost visibility (PRD R5 form half, R8; Decisions 8, 10; AC 4).
What changes at a high level: Add `RunPanel` with dataset select (last choice in guarded `localStorage`), split select from dataset splits plus all, and the test-split note. N input with blank = whole split, integer >= 1 validation and clamp on blur with note. Debounced 400 ms estimate showing the rough cost, or the server note with a pilot fallback when unknown. Optional max cost, prefilled at 1.5x the estimate rounded up, must be > 0 if set. Run disabled on invalid N or cost only. Empty-dataset message.
Done when: `RunPanel.test` covers validation, clamp, estimate known and unknown, blank cap allowed, persistence and no-datasets state.

## Task 8 — RunPanel run lifecycle
What it is / what it means: Starting, watching, aborting, downloading and re-attaching to runs (PRD R5 lifecycle half, R8; Decisions 6, 9; AC 5, 6, 8).
What changes at a high level: Run starts a run then polls the run via `usePolling`; show progress bar, failures, cost only if present, and Abort (disabled while aborting). Missing data (409 or flag) swaps Run for Download data, polling download status to ready or failed with Retry, then refetching datasets. Handle run_active with an attach button, attach on mount to any running run, verbatim schema_mismatch/backend_unreachable messages, the three-miss "Lost contact" banner, and a runs-list refresh signal on start, abort and terminal state.
Done when: fake-fetch and fake-timer tests cover download flow, progress, abort, 409 attach, reload attach, failed-run chip, and miss banner recovery.

## Task 9 — RunsList
What it is / what it means: Past runs table with resume and compare selection (PRD R6, R8; AC 7).
What changes at a high level: Add `RunsList` fetching on mount, on the refresh signal and via manual Refresh, with columns for select, date, dataset, split, N, schema, state chip, cost and failures; aborted_cost reads "aborted: cost cap". Resume appears for resumable states and finished-with-failures, disabled while another run is active. Row click sets the run view. Allow at most two ticks, disable cross-dataset ticks, enable Compare at exactly two to set the compare view. Empty message. Wire into `EvalApp` under the Run panel.
Done when: `RunsList.test` covers columns, resume matrix, tick limits, cross-dataset disable, navigation and empty state.

## Task 10 — Eval UI reference docs
What it is / what it means: User-facing reference for what D1 ships (PRD header ownership list; Manual steps).
What changes at a high level: Create `docs/reference/eval-ui.md` covering the toggle, Run panel, Runs list, proxy and env vars, empty/error states, and a section stub D2 appends to. Link it from `docs/reference/README.md`. Add an Eval tab note to `docs/reference/review-ui.md`. Include the owner manual checks as a closing note.
Done when: docs exist, link resolves, and `npm run typecheck && npm test && npm run build` pass.

## Owner manual checks (not tasks)
- Live smoke via `scripts/dev.sh` with provider keys: start a ~5-item pilot, close and reopen the tab mid-run in a real browser, confirm it re-attaches (live halves of AC 5 and AC 10).
- `/eval-api/health` through the Vite dev server against the real eval server.
