---
status: draft
summary: Audit|Eval toggle, frontend/src/eval/ shell (EvalApp, evalApi, usePolling), run form with estimate/download/progress/abort, runs list with resume and compare selection, Vite /eval-api proxy.
date: 2026-10-20
---
# PRD: D1 Eval shell & runs

Repo/branch: iaudit / `users/codex/eval-investigation` · Depends on: B4 (eval API + `eval-api.schema.json`; B1 already moved frontend validators to 1.1.0) · Owns: `frontend/src/App.tsx` (toggle only), `frontend/src/config.ts`, `frontend/src/env.d.ts`, `frontend/vite.config.ts`, `frontend/.env.example`, `frontend/src/eval/{EvalApp,evalApi,usePolling,RunPanel,RunsList,evalTypes,eval.css}` + tests + `fixtures/`, `docs/reference/review-ui.md` (Eval tab note), new `docs/reference/eval-ui.md` (D1 creates and links it from `docs/reference/README.md`; D2 appends its sections)

## TL;DR
Add a top-level **Audit | Eval** switch and the Eval tab's first two sections: a **Run** panel (dataset, split, N, estimate, max cost, Run/Download, progress, Abort) and a **Runs** list (Resume, tick two to Compare, click to open). All server access goes through one typed, never-throwing `evalApi` client behind the Vite `/eval-api` proxy. D2 plugs run detail, item detail and compare into the `EvalApp` view state created here.

## Problem
Frontend has one flow (upload → `POST /v1/audit` → `ReviewShell`) and no proxy, no polling, no second screen [verified: `App.tsx`; `vite.config.ts` has no `server.proxy`]. Eval runs spend money and last minutes, so the UI must show cost before start, survive tab close/reload, and never hide a stuck server.

## Goals / Non-Goals
**Goals**
- Switch Audit/Eval without touching Audit code paths.
- Start, watch, abort, resume runs; list past runs; choose two for compare.
- One client module whose types come from B4's schema, tested with injected fetch.

**Non-Goals**
- Run detail, metrics, items, gold panel, compare view (D2). Re-score button (D2, run detail).
- Router, state library, charts, styling beyond `app.css` conventions, auth.
- Concurrency/seed fields, Haiku/system dropdown, CLI, Eval mock mode (fake fetch in tests only). Run tags (e.g. contamination): no UI field in v1; start-run requests omit `tags` (B4 accepts it optionally, default unset).
- Any change to `ReviewShell`, `transport/`, `contract/`, or `docs/contracts/`.

## Requirements
**R1 Toggle.** `App` becomes a thin wrapper: `useState<"audit"|"eval">("audit")`, two buttons (`aria-pressed`), renders `<AuditApp/>` (today's `App` body moved verbatim, props `deps` kept) or `<EvalApp/>`. Conditional render (unmount), not hidden. Consequence: switching away discards the loaded audit and review selection (D brief §5.3 accepts); an in-flight audit is aborted by `useAuditLoader`'s unmount cleanup [verified: `useEffect` cleanup aborts controller]. Toggle bar sits above both; `Header` untouched. Existing `App.test.tsx` keeps passing via `deps` passthrough.

**R2 `evalApi.ts`.** Factory `createEvalApi({fetch, baseUrl="/eval-api"})` returning methods that resolve to `Result<T, EvalError>` and never throw (mirrors `postAudit`: `credentials:"omit"`, `AbortSignal` param, per-call timeout, JSON in/out, error body parsed). D1 implements all methods D1 and D2 need so D2 adds none: `health, listDatasets, getDataset, startDownload, getDownload, estimate, startRun, listRuns, getRun, abortRun, resumeRun, getMetrics, listItems, getItem, rescore, compare`. D1 only calls the first set; the rest are typed and unit-tested for path/body.
```ts
type EvalError =
  | { kind: "unreachable" }                      // fetch threw / 502 from proxy
  | { kind: "timeout"; seconds: number }
  | { kind: "cancelled" }
  | { kind: "api"; status: number; code: ApiCode; message: string; detail?: unknown }  // B4 error body
  | { kind: "bad_body"; message: string };       // non-JSON or fails schema check
type ApiCode = "invalid_request"|"not_found"|"run_active"|"bad_state"|"data_missing"|"backend_unreachable"|"schema_mismatch"|"forbidden"|"internal_error";
interface CallOpts { signal?: AbortSignal }
```
Timeouts: 10 s default (polls, lists), 30 s for POSTs (start run probes the backend). Response shapes are TS types hand-mirrored from B4's schema; a test validates every fixture with Ajv against `eval-api.schema.json` (R9), so drift fails CI.

**R3 `usePolling`.** `usePolling<T>(fn:(signal)=>Promise<Result<T,E>>, {intervalMs=1000, enabled, isTerminal})` → `{data, error, misses, stale}`. Runs once immediately, then sequentially (next tick scheduled after the previous resolves; no overlap). Stops when `isTerminal(data)` or `enabled=false`; aborts in-flight call and clears the timer on unmount. A failed poll keeps `data`, increments `misses`; success resets it; `misses >= 3` → caller shows banner (poll continues). Generation counter drops late results, as `useAuditLoader` does.

**R4 `EvalApp` shell.** State `{view:"list"} | {view:"run",runId} | {view:"item",runId,itemId} | {view:"compare",a,b}` via `useState`; D1 renders only `list` and, for the other three, a placeholder slot component `<ViewSlot view/>` that D2 replaces (D1 ships "Run detail — coming in D2" stub so row clicks are wired and testable). `EvalApp` owns one `evalApi` instance (prop `api?` for tests) and passes it down. On mount: `health()`; failure → "Eval server not reachable" banner + Retry, Audit tab unaffected.

**R5 `RunPanel`.**
- Dataset `<select>` from `listDatasets`; selection remembered in `localStorage` (try/catch). Split `<select>` from the dataset's `splits[]` plus `all`; reset on dataset change. Selecting split `test` shows the informational line from `DatasetMeta.test_split_note` (no confirm, no block).
- **N** input: blank = whole split; integer ≥ 1 else inline error and Run disabled; value > split size → clamped on blur with note "N clamped to {size}" (size from `DatasetMeta`; all-split = sum).
- **Estimate**: debounced (400 ms) `estimate({dataset,split,n})` on any change. Shows `~$X.XX for {n_items} items (rough)`. When `est_cost_usd === null` (B2 `basis: "none"`) shows the server `note` (fallback "Cost unknown — run a pilot (e.g. N=5) first"); Run stays enabled.
- **Max cost** field (USD, required, > 0; prefilled with 1.5 × estimate rounded up when known, else empty and Run disabled with hint). With unknown estimate the cap is still required.
- **Run** → `startRun`; on 202 immediately begins polling `getRun`. `data_missing` (409) or `data_present=false` replaces Run with **Download data**; click → `startDownload`, then poll `getDownload` until `ready|failed` (B2/B4 enum `not_downloaded|downloading|ready|failed`); show `downloading…`; `failed` shows API error text + Retry; `ready` refetches datasets and restores Run.
- **Progress** (while a run is active): bar `done/total`, failures, cost (`$—` when `progress.cost_known=false`), **Abort** (`abortRun`, disabled while aborting). Terminal states hide Abort and show the state chip, then the runs list refreshes.
- One active run only (B4): 409 `run_active` shows "Run {id} is already active" with a button that attaches progress to it. On mount, the panel scans `listRuns` for `state==="running"` and attaches (tab reload recovers a live run). `schema_mismatch` / `backend_unreachable` errors display the API message and `detail` versions verbatim.

**R6 `RunsList`.** Table from `listRuns` (refetched on mount, after start/abort/resume/terminal poll, plus manual Refresh): checkbox, Date, Dataset, Split, N (`n_items`), Schema, State chip, Cost (`totals.cost_usd`, `—` if null), failures. `aborted_cost` renders "aborted: cost cap". **Resume** button for `aborted|aborted_cost|interrupted|failed` and `finished` with `totals.failures>0` (B4 rule); disabled while another run is active. Row click (not checkbox/button) → `view:"run"`. Tick at most two; checkboxes for runs of a different dataset than the first tick are disabled; **Compare selected (2)** enabled at exactly two → `view:"compare"`. Empty: "No runs yet. Start one above." While a run is active the list row polls via the same `getRun` data (no second poller; list refetch on terminal).

**R7 Proxy & config.** `vite.config.ts`: `server.proxy["/eval-api"] = { target:"http://127.0.0.1:${IAUDIT_EVAL_PORT ?? 8100}", changeOrigin:false, rewrite: p => p.replace(/^\/eval-api/, "") }` (B4 serves at root). `changeOrigin:false` keeps `Host: localhost:5173`, which B4's Host/Origin allowlist accepts [verified: B4 PRD guards]; the dev server proxies, `vite preview` gets the same via `preview.proxy`. Env read in `vite.config.ts` via `loadEnv`. `config.ts` gains `evalBase: string` from optional `VITE_EVAL_API_BASE` (default `/eval-api`); `getConfig` stays non-throwing; `env.d.ts` and `.env.example` updated. Also: alias `@eval-api` → `../eval/api` plus `server.fs.allow` entry so tests/fixtures import `eval-api.schema.json` (answers B4 [OPEN]).

**R8 Empty/error states** (D brief §5.5, D1 rows): server down/502 → banner + Retry; no datasets → "No datasets in eval/datasets/"; data missing → Download; download fail → error + Retry; no runs; crashed/aborted/interrupted → chip + Resume; poll miss ×3 → "Lost contact with eval server — retrying" banner (run continues server-side); N clamp note; compare checkbox disabling. (Scoring spinner, item and compare states belong to D2.)

**R9 Tests** (per `docs/testing/frontend.md`: co-located, jsdom opt-in per file, injected fetch, no real network):
| File | Proves |
|---|---|
| `evalApi.test.ts` | path/method/body per method; error mapping (network, timeout, cancel, each ApiCode, non-JSON); never throws |
| `usePolling.test.tsx` | fake timers: 1 s cadence, no overlap, stops on terminal, unmount aborts and stops fetching, 3 misses flag then recovery |
| `RunPanel.test.tsx` | validation/clamp, estimate display incl. unknown, Run disabled rules, Download→status→Run, progress+Abort, 409 attach, reload attaches to running run |
| `RunsList.test.tsx` | columns, Resume visibility matrix, ≤2 ticks, cross-dataset disable, Compare/row navigation, empty |
| `App.test.tsx` (extend) | toggle switches views; Audit idle prompt intact; toggle to Audit mid-run → zero further fetches |
| `fixtures.test.ts` (eval) | every fixture in `src/eval/fixtures/` validates against `eval-api.schema.json` `$defs` via `x-routes` |

## Architecture
```
frontend/src/
  App.tsx                 toggle; AuditApp = old body
  eval/
    EvalApp.tsx           view state, owns api, health banner
    evalApi.ts            createEvalApi(...) -> EvalApi
    evalTypes.ts          Result-aligned types mirrored from eval-api.schema.json
    usePolling.ts
    RunPanel.tsx  RunsList.tsx  ViewSlot.tsx(D1 stub, D2 replaces)
    fixtures/*.json       validated against schema
```
Shared with D2: `EvalApp` view union, `EvalApi`/`EvalError` types, `usePolling`, `evalTypes.ts`, fixtures, the `selection` pair handed to `compare`. Boundary: `eval/` imports `Result` from `contract` and nothing from `transport/` internals except patterns copied in shape (D brief boundary rule); `App` knows only the toggle.

## Decisions
| # | Decision | Choice | Alternatives considered | Why |
|---|---|---|---|---|
| 1 | Toggle mechanism | Conditional render in wrapper `App` | Keep both mounted/hidden | Hidden Audit keeps in-flight request and selection alive; D brief accepts discard; simpler |
| 2 | Audit body | Move into `AuditApp`, same file | New file | Zero diff in behaviour; tests unchanged |
| 3 | Client style | Factory with injected fetch, `Result`, never throws | Free functions; class | Matches `postAudit` DI/test style |
| 4 | API types | Hand-mirrored TS + Ajv fixture test vs B4 schema | Codegen from schema | No new dependency/build step; drift still caught in CI |
| 5 | Poll loop | Sequential setTimeout, keep last data on miss | `setInterval` | No overlap/pile-up on slow server |
| 6 | Single poller | RunPanel's `getRun` poll only; list refetches on terminal | Poll `listRuns` too | B4 allows one active run; fewer calls |
| 7 | Proxy Host | `changeOrigin:false` | `true` | B4 Host/Origin allowlist expects localhost:5173 |
| 8 | Max cost with unknown estimate | Required field, no default | Allow blank = uncapped | B2 cap only enforceable if costs known; forces explicit choice |
| 9 | Run attach on reload | Scan `listRuns` for `running` | Persist run id in localStorage | Server is source of truth; survives cleared storage |
| 10 | Persistence | Last dataset only, `localStorage` try/catch | Persist split/N/view | Brief §5.3 |

## Manual steps
- Live smoke (owner): `scripts/dev.sh` with provider keys; start a ~5-item pilot, close and reopen the tab mid-run, confirm it re-attaches.

## Risks / Open Questions
- [RESOLVED: B4 passes B2's `Estimate` through unchanged (`basis` `prior_runs`|`none`, `note`)] Cold-start note text comes from the server.
- [RESOLVED: B4 `DatasetSummary.splits[]` = `{name, size|null}`; `DatasetMeta` adds descriptions and `test_split_note`] D1 still calls both on dataset change, but sizes are available from the list.
- [RESOLVED: assumed sufficient] `state=aborted_cost` renders "aborted: cost cap"; no extra reason field.
- [OPEN] `max_cost_usd` is required by B4 `POST /runs`, but with no `run_info.cost_usd` (cost_usd is optional, omitted when the backend has no price) the cap is unenforceable. B2 records `cost_known=false` plus a warning; D1 shows a warning when `progress.cost_known=false`. Fail-closed `require_cost` is a user decision (see B2 Risks).
- [RESOLVED: B4 commits `eval/api/eval-api.schema.json` (bundling B3's schemas) before D1 tests run; D1 R7 adds the alias and `fs.allow`] Schema location. Pre-B4 fallback: assume the sketch above.
- [RESOLVED: B4 decision 7] Prefix stripped by proxy `rewrite`, server serves at root.
- [RESOLVED: B4 decision 3] One run at a time, so one progress panel.
- [DEFERRED] Item-list pagination (D2). Concurrency, seed field in UI.
- [DEFERRED] Production (`vite preview`/hosted) proxy beyond `preview.proxy`; local dev only.

## Acceptance Criteria
1. `npm run typecheck && npm test && npm run build` pass; existing Audit tests unchanged and green.
2. Toggle shows Audit (idle prompt) by default; switching to Eval shows Run + Runs sections; back to Audit shows a fresh idle state.
3. With the eval server stopped, Eval shows the "not reachable" banner with Retry; Audit still works.
4. Estimate known → shown as rough; unknown → "run a pilot" text; blank/invalid N or missing max cost disables Run; N above split size is clamped with a note.
5. Run → progress bar updates ~1 s, Abort stops it; reload mid-run re-attaches; closing the tab does not stop the run.
6. Missing data shows Download with status and error/Retry; completion restores Run.
7. Runs list shows all columns, Resume only for resumable states, max two same-dataset ticks, Compare and row click set the D2 views.
8. 3 consecutive poll failures show the banner; recovery clears it; unmount/toggle stops all polling (fake-timer test).
9. All eval fixtures validate against `eval/api/eval-api.schema.json`.
10. `/eval-api/health` through the Vite dev server reaches the eval server (manual or stub-server test).
