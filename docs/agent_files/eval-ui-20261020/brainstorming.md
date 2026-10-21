---
status: approved
summary: Eval UI in the existing frontend: Audit|Eval toggle, run/monitor/score/compare evals, and reuse the read-only left/right review view for any saved item.
date: 2026-10-20
---

# Eval UI (project D) brainstorming

## 1. TL;DR

- Add a top-level **Audit | Eval** toggle. Audit is today's upload view, unchanged.
- Eval = Run section (dataset, split, N, cost estimate, progress) + Runs list -> run detail (metrics, run info) -> item list -> item detail.
- Item detail = a small **gold panel** above the **existing** `ReviewShell`, fed from the saved request + response (no re-run).
- UI is a thin client of the eval API owned by project B (`/eval-api`, proxied by Vite). No new state store, no DB, no router library.
- Plain tables, no charts, no auth, no cross-dataset headline score.

## 2. Problem

| Today | Gap |
|---|---|
| Frontend audits one uploaded request at a time | No way to run a dataset, see aggregate quality, or compare runs |
| Eval (B, C) is CLI/API only | Metrics, per-item mismatches and run provenance are not inspectable by eye |
| Review view needs a `LoadResult` from an upload | Eval items must open in the same view without re-calling the LLM |

Goal: run, watch, score, inspect and compare evals locally, reusing what exists. Mission fit: the review tool stays the way a human inspects a discrepancy; the eval UI only measures the audit, it does not change audit behaviour or scope.

## 3. Decision log

| Decision | Alternative rejected | Why |
|---|---|---|
| Top-level Audit \| Eval toggle in `App` | Separate app / route library | Smallest change; one dev server; Audit stays untouched |
| Toggle state is plain `useState`, not a router | react-router / URL routes | Single user, local; no deep links needed |
| Eval is a thin client of project B's eval API | Frontend reads `eval/runs/` files directly | Browser cannot read disk; API owns formats and long-running work |
| Vite proxies `/eval-api` to the eval port | Direct cross-origin calls + CORS | Same origin, no CORS config; mirrors "no cookies" stance |
| Runs execute in the eval server; UI polls | UI holds the run open (SSE/WebSocket) | Closing the tab must not kill a run; polling is trivial to test |
| Poll interval ~1 s while a run is `running` | Push channel | Simplicity; local server, negligible load |
| Dataset dropdown = one entry per `eval/datasets/` folder | Hard-coded TofuEval | Custom datasets later with no UI change |
| Split dropdown from `metadata.json`, incl. "all" | Free-text split | Prevents invalid splits |
| N blank = whole split; else N seeded-random | Always first N | Seeded random is representative and reproducible; seed shown in run info |
| Missing data -> Download button replaces Run | Auto-download on Run | Download is a visible, separate, fetch-from-network step |
| Cost estimate before start + max-cost abort | Show cost only after | Runs spend real money; abort bounds surprise |
| Concurrency default 4, not exposed as a field in v1 | Concurrency control in UI | Basic UI; server flag if needed (see risks) |
| Scoring runs automatically on finish; Re-score button | Manual score only | Common path needs no click; re-score covers metric/mapping changes, no LLM calls |
| Resume button for crashed/aborted runs (redo failed/missing only) | Start a new run | Saves cost, keeps one run identity |
| Item detail reuses `ReviewShell`, read-only | New bespoke item viewer | Mission part 2 already is that viewer; zero duplication |
| Gold panel is a separate component above the shell | Injecting gold into `LeftPane`/`RightPane` | Keeps review components unchanged; boundary is clear |
| Saved request+response replayed through `validateResponse` + `analyzeResponse` | Trusting stored JSON | Reuses existing checks; stale-schema runs fail visibly |
| Compare = tick two runs of the same dataset, plain table | Chart / multi-run matrix | User wants basic; deltas and disagreements are tables |
| Paper rows greyed, labelled "paper-reported, different model & date" | Hide or mix with ours | Honest comparison; not a like-for-like benchmark |
| Show failures count, primary (failure = wrong) and secondary (excluded) scores | One score | Failures otherwise silently inflate or deflate results |
| Test-split note is informational ("reporting, not tuning") | Block or confirm dialog | User chose no action required |
| Run info block at bottom of run detail | Header or separate page | Provenance matters but is secondary to metrics |
| Haiku baseline / system dropdown scrapped | System selector | Out of scope per user |
| No cross-dataset headline score | Aggregate number | Out of scope per user |
| No auth, hosting, fancy styling | Any | Local single-user tool |

## 4. Current frontend (as-is, verified from code)

Stack: Vite 8, React 19, strict TS, Ajv, Vitest 5 (`frontend/package.json`). No router, no state library, no UI kit. `vite.config.ts` has a `@contracts` alias to `docs/contracts/` and no `server.proxy` today. `scripts/dev.sh` and `eval/` do not exist yet (checked).

### Upload -> run -> review flow

| Step | Code | Behaviour |
|---|---|---|
| 1. Pick file | `Header.tsx` hidden `<input type=file>` + "Upload request..." button | Calls `onFile(file)` |
| 2. Load | `App.tsx` -> `useAuditLoader(deps)` `loadFile` | State machine `idle -> loading -> ok \| error`; generation counter + `AbortController` drop stale results |
| 3. Read | `runAudit.ts` `readRequestFile` | Strips BOM, rejects empty/non-JSON, `validateRequest` |
| 4. Send | `auditRequest` -> `client.ts` `postAudit` (or `mock/registry.ts` `lookupMock` when `VITE_MOCK=true`) | POST JSON to `VITE_AUDIT_URL`, no cookies, 120 s timeout; never throws |
| 5. Check | `validateResponse(raw, request)` then `analyzeResponse` | Version, schema, `request_id`, duplicate ids; per-claim span checks |
| 6. Result | `LoadResult { ok, request, response, analysis, source }` | `source` is `"mock"` or `"service"` |
| 7. Render | `App` -> `<ReviewShell key={loadId} result headerProps />` | `ReviewShell` remounts per load |

### Review view

| Component | Role | Props it needs |
|---|---|---|
| `ReviewShell` | Owns `useReducer(reviewReducer)`, scroll-on-navigate, renders `Header` + verdict counts + `WarningsBanner` + `<main>` with panes | `result: LoadResult`, `headerProps` |
| `LeftPane` | Section cards, `ClaimText` underlines, unplaced-claims cards | `request, response, analysis, state, onSelect, onNavigate` |
| `RightPane` | Stepper + `ClaimDetail` for selected claim | `request, analysis, state, onStep` |
| `Header` | Upload button, filename, request id, "Mock data" chip, verdict counts | `inputRef`, `onFile` required |

Selection state is internal to `ReviewShell`; nothing is shared with `App`.

### What the eval UI reuses

| Reuse as-is | Reuse with a small wrapper | New |
|---|---|---|
| `ReviewShell`, `LeftPane`, `RightPane`, `ClaimDetail`, `WarningsBanner` | Building a `LoadResult` from saved JSON: new helper calling `validateRequest`/`validateResponse`/`analyzeResponse` (same functions `auditRequest` uses; `auditRequest` itself cannot be used because it does a network call) | Toggle, `eval/` components, eval API client, gold panel |
| `contract/*` validators and analysis | `Header`: item view needs it without the upload button (Unverified: either pass no-op props or add optional hiding; decide in implementation) | |
| `tokens`, `app.css`, error-screen styling patterns | `postAudit` pattern (abort reasons, never-throw `Result`) copied in shape for the eval client | |

Unverified: whether `LoadResult` fields beyond those listed in `errors.ts` exist (read from `runAudit.ts` only; `errors.ts` not opened). Also unverified: the 1.1.0 contract change (optional `run_info`) and whether `validateResponse` pins `schema_version` to `1.0.0` (the reference doc says it does), which would reject 1.1.0 replies until the validator is bumped.

## 5. Design

### 5.1 Screens

**Top bar**

```
[ Audit | Eval ]                     (Audit = today's page)
```

**Eval: Run section + runs list**

```
Run
 Dataset [TofuEval v]  Split [dev v]  N [____] (blank = all)
 Est. cost: ~$3.20 for 120 items   Max cost [$ 5.00]
 [ Run ]            or   data missing -> [ Download data ]
 Progress: [#######-----] 70/100  failures: 2   [Abort]

Runs
 [ ] Date              Dataset   Split N   Schema  Status     Cost
 [ ] 2026-10-20 10:02  TofuEval  dev   100 1.1.0   done       $2.90
 [ ] 2026-10-19 16:40  TofuEval  test  50  1.1.0   aborted    $0.70  [Resume]
 [Compare selected (2)]
```

**Run detail: metrics**

```
Run 2026-10-20 10:02  TofuEval dev N=100   [Re-score]
Failures: 2   Primary (failure = wrong)  Secondary (excluding failures)
Metric        Value  n    CI           Slice    Primary  Secondary
bal-acc       0.71   98   0.64-0.78    overall  ...
 paper: ...   0.69   -    -            overall  (grey) "paper-reported, different model & date"
Items (below)
Run info: commit abc123 (dirty) | models per tier | prompt hashes |
          mapping version | seed | note (test split): "test runs are for
          reporting, not tuning"
```

**Item list**

```
Filter: [all | mismatch | failed]
Item        Gold   Ours   Match
doc-0012    incons consis  x
doc-0013    consis consis  ok
```

**Item detail**

```
< back to run
+ Gold panel -------------------------------------+
| sentence 1: consistent                           |
| sentence 2: inconsistent - type: ... "explanation"|
+--------------------------------------------------+
[existing ReviewShell: left assessment | right claim detail] (read-only)
```

**Compare view** (two runs, same dataset)

```
Metric deltas on shared items (n shared = 96)
Metric   Run A  Run B  Delta
Disagreements (items where A and B differ)
Item     Gold   A      B
```

### 5.2 Components and boundaries

| Component (new, in `frontend/src/eval/`) | Responsibility | Depends on |
|---|---|---|
| `EvalApp` | Eval section state: selected run, view (`list`/`run`/`item`/`compare`) via `useState` | children |
| `RunPanel` | Dataset/split/N form, estimate, Run/Download, progress | `useDatasets`, `useRunProgress` |
| `RunsList` | Table, tick up to two, Resume, Compare | `evalApi` |
| `RunDetail` | Metrics table, failures, Re-score, `RunInfo` | `evalApi` |
| `MetricsTable` | Our rows + grey paper rows | pure props |
| `ItemList` | Gold vs ours, filter | `evalApi` |
| `ItemDetail` | Loads item, builds `LoadResult`, renders `GoldPanel` + `ReviewShell` | `ReviewShell`, `contract/*` |
| `GoldPanel` | Per-sentence gold labels, explanations, types | pure props |
| `CompareView` | Delta table + disagreements | `evalApi` |
| `evalApi.ts` | Typed fetch wrappers, `Result` style, never throws | `fetch` injected |
| `usePolling` | Interval hook, stops on terminal status, cancel on unmount | none |

Boundary rules: only `ItemDetail` touches review components; `App` knows only the toggle; eval components never import from `transport/` except shared `Result`/error patterns; no change to `reviewState`, `LeftPane`, `RightPane`.

### 5.3 State and data flow

| State | Lives in | Notes |
|---|---|---|
| Audit | `useAuditLoader` (unchanged) | Kept mounted/unmounted on toggle; switching away discards review selection (acceptable) |
| Eval view/selection | `EvalApp` `useState` | No persistence beyond optional last-selected dataset in `localStorage` (try/catch) |
| Active run progress | Server; `usePolling` reads `GET runs/{id}` | Reloading the tab re-finds any run with status `running` from the list |
| Item data | Fetched on open; one `LoadResult` per open item | `key` = run+item so `ReviewShell` remounts |

Flow: dropdowns <- datasets API; Run -> `POST runs` -> poll -> on `done` server scores -> metrics fetched -> items -> item detail builds `LoadResult` -> `ReviewShell`.

### 5.4 Eval API consumed (sketch; owned by project B, contract to be confirmed there)

All paths under `/eval-api`. Names and shapes are proposals, not verified.

| Need | Endpoint (proposed) | Returns |
|---|---|---|
| List datasets | `GET /datasets` | `[{name, title, data_present}]` |
| Dataset metadata | `GET /datasets/{name}` | `metadata.json` (splits, sizes) |
| Download data + status | `POST /datasets/{name}/download`; `GET /datasets/{name}/download` | `{status, error?}` |
| Cost estimate | `POST /runs/estimate` `{dataset, split, n, seed?}` | `{items, est_cost_usd}` |
| Start run | `POST /runs` `{dataset, split, n, max_cost_usd}` | `{run_id}` |
| Progress | `GET /runs/{id}` | `{status, done, total, failures, cost_usd}` |
| List runs | `GET /runs` | summaries |
| Run detail / metrics | `GET /runs/{id}` + `GET /runs/{id}/metrics` | report JSON list `{metric,value,n,ci,slice,impl}` + paper refs + run info |
| Item list | `GET /runs/{id}/items` | `[{item_id, gold, pred, match, failed}]` |
| Item detail | `GET /runs/{id}/items/{item}` | `{request, response, gold}` |
| Re-score | `POST /runs/{id}/rescore` | updated status |
| Resume | `POST /runs/{id}/resume` | status `running` |
| Abort | `POST /runs/{id}/abort` | status `aborted` |
| Compare | `GET /compare?a=&b=` | `{shared_n, deltas[], disagreements[]}` |

### 5.5 Failure and empty states

| Situation | UI |
|---|---|
| Eval server down / proxy 502 | Banner "Eval server not reachable" + Retry; Audit tab unaffected |
| No datasets found | "No datasets in eval/datasets/" |
| Data missing | Download button instead of Run |
| Download fails | Error text from API + Retry |
| No runs yet | "No runs yet. Start one above." |
| Run crashed / aborted | Status chip + Resume |
| Max-cost abort hit | Status "aborted: cost cap"; Resume allowed |
| Some items failed | Failure count; failed items flagged in list; no review view (no response) |
| Metrics not ready (scoring) | "Scoring..." spinner; Re-score disabled |
| Saved response fails validation (older schema) | Item shows existing invalid-response `ErrorScreen`; run still listed |
| Compare, different datasets | Checkbox disabled for non-matching dataset |
| Compare, no shared items | "No shared items" |
| N larger than split | Clamp, show note |
| Poll fails once | Keep last state, retry next tick; after 3 misses show banner |

### 5.6 Testing approach (matches `docs/testing/frontend.md`)

| Layer | Approach |
|---|---|
| Convention | Tests next to code (`*.test.ts(x)`), Vitest + Testing Library + jsdom; no real network |
| `evalApi` | Inject `fetch`; assert paths, bodies, error mapping (same as `client.test.ts`) |
| `usePolling` | Fake timers; stops on terminal status; unmount cancels |
| Components | `MetricsTable`, `ItemList`, `GoldPanel`, `RunPanel` with fixture props |
| Item detail | Build `LoadResult` from an existing `docs/contracts/examples/` pair + fake gold; assert `ReviewShell` renders |
| E2E | `eval/mock-flow.test.tsx`: fake fetch driving select dataset -> run -> poll -> metrics -> item -> compare |
| Fixtures | Eval API fixtures kept in `frontend/src/eval/fixtures`; a test validates them against B's schema once it exists |
| Gates | `npm test`, `npm run typecheck`, `npm run build`; add eval flow to the release checklist |

## 6. Non-goals

| Not doing |
|---|
| Auth, hosting, multi-user, DB |
| Fancy styling, charts |
| Cross-dataset headline score |
| Haiku baseline / system dropdown |
| Editing gold labels or audit outputs |
| Re-running a single item from the UI |
| Concurrency field in UI (default 4) |
| Diagnosis, scoring rules or protocol review (mission) |
| Mock-mode support for the eval tab (use fake fetch in tests only) |

## 7. Open risks and cheapest tests

| Risk | Cheapest test |
|---|---|
| Frontend validator rejects 1.1.0 (`schema_version` pinned to 1.0.0) | Run `validateResponse` on a 1.1.0 sample; fix by bumping once contract lands |
| `Header` requires upload props, awkward in item view | Spike: render `ReviewShell` with no-op props and confirm the layout |
| Vite proxy not in place; `scripts/dev.sh` absent today | One-line `server.proxy` check with a stub server |
| Eval API shape differs from sketch | Agree a shared JSON schema with B before coding; contract test against fixtures |
| Gold panel misreads TofuEval labels/types (project C schema) | Render from one real C item; compare by eye with source |
| Saved request+response large -> slow item open | Open the largest saved item; check time and memory |
| Polling leaks after toggle/unmount | Test: toggle to Audit mid-run, assert no more fetches |
| Cost estimate inaccurate (needs `run_info` tokens/cost, tier prices) | Compare estimate vs actual on a 5-item run |
| Compare on shared items biased by seeded N subsets | Show shared n prominently; test with partially overlapping runs |
| Mixed-schema runs (old 1.0.0 saved items) fail to open | Test one stale run; expect clear error, not a crash |

## 8. Links

- [eval-core (B)](../eval-core-20261020/brainstorming.md)
- [eval-tofueval (C)](../eval-tofueval-20261020/brainstorming.md)
- [taxonomy-v1 (A)](../taxonomy-v1-20261020/brainstorming.md)
- [Investigation](../users-codex-eval-investigation-20261020-035707/INVESTIGATION.md)
- Frontend internals: `docs/implementation/frontend.md`; testing: `docs/testing/frontend.md`
