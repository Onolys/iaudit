---
status: draft
summary: Eval run results and drill-down in the existing frontend - run detail (metrics, paper rows, re-score, run info), item list, read-only item detail via the unchanged ReviewShell plus a GoldPanel, failed-item view, and two-run compare.
date: 2026-10-20
---
# PRD: D2 Results & items

Repo/branch: iaudit / `users/codex/eval-investigation` · Depends on: D1 (EvalApp, `evalApi`, `usePolling`, runs list), B3 (metrics + compare shapes), B4 (endpoints + `eval/api/eval-api.schema.json`), C2 (TofuEval gold shape) · Owns: `frontend/src/eval/{RunDetail,MetricsTable,RunInfoBlock,ItemList,ItemDetail,FailedItem,CompareView,buildLoadResult}.tsx|ts`, `frontend/src/eval/gold/` (`GoldPanel`, `TofuEvalGold`, `GenericGold`), `frontend/src/eval/fixtures/` (results/items/compare), their tests; small edits to shared files listed under Architecture

## TL;DR
Click a finished run: see metrics (ours + greyed paper rows, primary vs secondary, failures, n, CI), a Re-score button, the item list (all / mismatch / failed), and a run-info block. Click an item: the saved request+response replay through the existing validators into `ReviewShell` (read-only, no LLM call) under a dataset-aware `GoldPanel`. Failed items show error info only. Pick two runs of one dataset: delta table on shared items plus a disagreements list that click through to items. Plain tables, no charts.

## Problem
D1 gets a run started and listed. Nothing yet answers "how good was it, where did it go wrong, and why" - the metrics, provenance and the per-item view that makes a mismatch inspectable by eye (brief §2). The review view needs a `LoadResult`, which today only `auditRequest` produces via a network call.

## Goals / Non-Goals
**Goals**
- Metrics honest about failures and about paper comparability.
- Any saved item opens in the existing review view; stale/invalid saved data fails visibly, never crashes.
- Gold shown next to ours without touching `LeftPane`/`RightPane`/`reviewState`.
- Compare shows how many items it is based on.

**Non-Goals**
- Run form, progress, runs list, toggle, proxy (D1). Metric computation, CIs, compare maths (B3). Gold/projection logic (C).
- Charts, pagination, sorting, per-item re-run, editing gold, highlight of gold sentences inside `LeftPane` (see D6), next/previous item stepping, cross-dataset score.

## Requirements
**R1 RunDetail** (props `runId`, `onOpenItem(itemId)`, `onBack`). Fetches `GET /runs/{id}` and `/metrics` (404 `not_found` is not an error, see R2). Layout, top to bottom: title (dataset, split, N, date) + state chip + Re-score; failures line; `MetricsTable`; `ItemList`; `RunInfoBlock`.
**R2 Scoring state**. `score_state` `pending|running` -> "Scoring..." in place of the table, Re-score disabled, poll `GET /runs/{id}` via D1 `usePolling` until `done|failed`, then refetch metrics. `failed` -> message + Re-score enabled. Re-score is also disabled while run `state` is `running` (server returns 409 `bad_state` [verified: B4]). Click -> `POST /runs/{id}/rescore`, then the same polling path. No LLM calls (server-side, B3).
**R3 MetricsTable** (pure props). Rows grouped under a heading per `level`, then `slice` (B3 keeps them as separate fields), in server order. Each metric shows its `primary` (failures = wrong) and `secondary` (failures excluded) entries side by side: value, n, CI. `n_clusters` is available on hover; when `ci_status` is `few_clusters` or `undefined` the CI cell shows `-` with that status as a hint. `policy: none` entries (`failure_rate`, `coverage`) feed the failures line. Failures line above: "Failures: k of N. Primary counts them wrong; secondary excludes them." Paper reference rows follow the matching metric, greyed (`.is-reference`), labelled "paper-reported, different model & date", value only, `-` elsewhere; `reference_caveats` shown in a collapsed note. A small `toMetricRows(report)` normalizer is the only code that knows the B3 report shape.
**R4 RunInfoBlock** (bottom). git commit + "(dirty)"; models per tier; prompt hashes (first 8 chars, full in `title`); mapping version; seed; tags (e.g. contamination) when set; total cost (`totals.cost_usd` null -> "unknown"); a "mixed fingerprint" warning when `run_info.mixed`, and any `warnings` listed. `split === 'test'` adds an informational line "Test runs are for reporting, not tuning." (no button, no dialog).
**R5 ItemList**. Filter radio all | mismatch | failed -> `GET /runs/{id}/items?filter=`; one request with a high `limit` (no paging UI). Columns: Item (`label ?? item_id`), Gold, Ours, Match (check / cross / `-`), Status chip for failed. Row click -> `onOpenItem`. Empty: "No items match this filter." A filter change keeps the table visible and dims it while loading.
**R6 ItemDetail** (props `runId`, `itemId`, `onBack`, `backLabel`). Fetch `GET /runs/{id}/items/{item}` (id passed through `encodeURIComponent`; B2 ids are filename-safe, so this is defensive). Branch:
| Item | Render |
|---|---|
| loading / fetch error | text / Retry (same `Result` style as D1) |
| `status ok`, `response` present | `buildLoadResult` -> ok: back bar + `GoldPanel` + `<ReviewShell key={run/item}>`; error: back bar + `GoldPanel` + existing `ErrorScreen` |
| `status failed` (`response` null) | back bar + `GoldPanel` + `FailedItem` |
**R7 buildLoadResult** `(request: unknown, response: unknown): Result<LoadResult, LoadError>`. `validateRequest`, then the same response checks `auditRequest` runs, then `analyzeResponse`; `source: "service"`. No network, no `JSON.parse` (server already parsed). Stale 1.0.0 responses fail as `invalid_response/wrong_version` after B1 bumps the pin to 1.1.0 [verified: `validate.ts` pins `"1.0.0"` today; B1 owns the bump]. After A1 moves the pin to 1.2.0, items saved under 1.1.0 (e.g. the pre-A1 baseline run) fail the same way in the item view; metrics, compare and lists are unaffected (see Risks).
**R8 FailedItem**. No review view. Shows `failure.kind`, HTTP status, `error_code`, message and up to 50 `issues` (path: message, as `ErrorScreen` does). Fields are all optional (B2 item `failure`, passed through as B4 `ItemDetail.failure`); missing ones are omitted. States "No response was saved. Resume the run to retry."
**R9 GoldPanel** `({goldKind, gold})`. Looks up a renderer by `gold_kind`; unknown kind or renderer shape mismatch -> `GenericGold` (pretty-printed JSON in a collapsed `<details>`). `TofuEvalGold` (`gold_kind` `tofueval_summary_sentences`; shape from C2 R1: `{summary, sentences[{sent_idx, text, label, types, exp, start, end}]}`, delivered in `ItemDetail.gold`) lists per sentence: index, text, label (consistent / inconsistent), error types (as native strings), explanation. Collapsible, `max-height: 30vh` scroll, so the review view keeps most of the screen. Not a review component; never imports from `app/`.
**R10 CompareView** (props `aRunId`, `bRunId`, `onOpenItem(runId, itemId)`, `onBack`). `GET /compare?a=&b=`; 409 across datasets surfaces as an inline error. Shows run labels, "n shared = k" (`n_shared`) prominently, delta table (metric, level, slice, A, B, delta, delta CI when `ci_status` ok; delta signed, no colour judgement), disagreements list (item, and per differing pair: level, unit, gold, A, B). "No shared items" when `n_shared` is 0. Each disagreement has "open in A" / "open in B"; the item's back button returns to the compare view (`backLabel` "Back to comparison").
**R11 Failure states**: eval server unreachable -> D1's banner component with Retry; metrics 404 with `score_state done` -> "Metrics missing. Re-score." Poll misses follow D1's 3-miss rule.

## Architecture
```
EvalApp (D1) view: {kind:'list'} | {kind:'run', runId}
                 | {kind:'item', runId, itemId, from:'run'|'compare', cmp?:[a,b]}   <- D2 adds
                 | {kind:'compare', a, b}                                           <- D2 adds
RunDetail -> MetricsTable, ItemList, RunInfoBlock
ItemDetail -> buildLoadResult -> GoldPanel + ReviewShell(result, headerProps) | ErrorScreen | FailedItem
```
Interfaces (types come from `eval-api.schema.json`, which bundles B3's `metrics.schema.json`/`compare.schema.json`):
```ts
export function buildLoadResult(request: unknown, response: unknown): Result<LoadResult, LoadError>;
export interface GoldPanelProps { goldKind: string; gold: unknown }
type GoldRenderer = ComponentType<{ gold: unknown }>;      // registry: Record<string, GoldRenderer>
// MetricsReport entry (B3 R7): { metric, level, policy: 'primary'|'secondary'|'none', slice: {}, value|null, n, n_clusters, ci: [lo,hi]|null, ci_status, impl }, plus references[], reference_caveats[]
// Comparison (B3 R9): { n_shared, n_a_only, n_b_only, deltas: {metric, level, policy, slice, a, b, delta, delta_ci, ci_status}[], disagreements: {item_id, cluster, pairs: {level, unit, gold, a, b}[]}[] }
```
**Shared-file edits** (each minimal, all tested):
| File | Change | Why |
|---|---|---|
| `app/Header.tsx` | `inputRef`, `onFile` become optional; hidden input + Upload button render only when `onFile` is set | Item view has no upload; `ReviewShell` already forwards `headerProps` untouched. Audit passes both, so behaviour is identical. `fileName` carries "run - item", `requestId` the request id |
| `transport/runAudit.ts` | Extract the post-parse response checks into an exported helper used by `auditRequest` and `buildLoadResult` | One error mapping, not two copies |
| `transport/ErrorScreen.tsx` | `onChooseFile` optional; "Choose another file" hidden when absent | Item errors have no file to choose |
| `eval/EvalApp.tsx`, `eval/evalApi.ts` (D1) | Add the two view kinds; add `getMetrics`, `rescore`, `listItems`, `getItem`, `compare` wrappers | Same never-throw `Result` pattern as D1 |
`ReviewShell`, `LeftPane`, `RightPane`, `reviewState`, `ClaimDetail` untouched.

## Decisions
| # | Decision | Choice | Alternatives considered | Why |
|---|---|---|---|---|
| D1 | Header without upload | Make `inputRef`/`onFile` optional | No-op props + hidden CSS; separate `ItemHeader` | A no-op button invites clicks; a copy drifts from `Header` |
| D2 | `LoadResult` for saved items | Shared helper extracted from `auditRequest`, `source: "service"` | Call `auditRequest` with a fake fetch; copy the mapping | Fake fetch is test-only machinery in prod; copy duplicates error mapping |
| D3 | Remount | `key = runId/itemId` on `ReviewShell` | Reset action in `reviewState` | Same pattern as `loadId`; no review code change |
| D4 | Stale/invalid saved data | Existing `ErrorScreen` | New item-error component | Locked decision; same wording as Audit |
| D5 | Metrics shape isolation | `toMetricRows` normalizer + schema-validated fixtures | Components read the report directly | B3 PRD not final; one place to fix |
| D6 | Highlight gold sentence in the text | Not in v1 | Pass offsets into `ClaimText` | Needs `LeftPane`/`ClaimText` changes, which the boundary rule forbids; the panel already shows sentence text. Revisit if C1's offset map ships in gold and a prop on `ReviewShell` is approved |
| D7 | Item list loading | One request, all rows | Paging / virtual list | Max 1,777 rows [verified: C brief]; plain table is fine |
| D8 | Compare click-through | Open the item in A or B separately | Side-by-side two review views | Locked basic scope; the review view is single-result |
| D9 | Gold registry | `Record<gold_kind, renderer>` + JSON fallback | Hard-coded TofuEval | Locked; new dataset needs one entry, no UI rewrite |

## Manual steps
- Eyeball one real TofuEval item (gold panel vs source CSV) after C2 data is downloaded: needs the user's local download and a paid run [owner only].

## Risks / Open Questions
- [RESOLVED: B3 R7] Primary vs secondary are separate entries with `policy`; field names per the interface comment above; only `toMetricRows` and fixtures depend on them.
- [RESOLVED: C2 R1] `gold_kind` is `tofueval_summary_sentences`; gold shape as in R9. `TofuEvalGold` still guards the shape and falls back to JSON.
- [RESOLVED: B4 `ItemDetail.failure` = B2 item `failure` verbatim; `RunDetail.run_info` includes `mapping_version`, `tags`, `mixed`, `warnings`] Mixed-fingerprint runs are flagged in `RunInfoBlock` (R4).
- [RESOLVED: B3 R8 `ItemRow` (`gold`/`pred` display strings, `match`, `outcome?`, `detail?`), filled by the adapter `item_row` hook (C2)] Item list columns.
- [RESOLVED: D1 creates `docs/reference/eval-ui.md` (listed in D1 Owns); D2 appends its sections] Who creates the eval UI reference. D2 adds the two view kinds to D1's `EvalApp` view union.
- [RESOLVED: B1 owns the pin bump] Frontend rejects 1.1.0 until `validate.ts` is changed; D2 depends on B1 landing first.
- [OPEN] After A1 moves the contract to 1.2.0, `ItemDetail` rejects items saved under 1.1.0 (`wrong_version`), including the pre-A1 baseline run that A1's before/after is measured against. Metrics, compare and lists still work. Options: accept (open baseline items on the pre-A1 checkout) or let D2 replay saved items with the version they were saved under. Needs the user's call before A1 lands.
- [RESOLVED: show only] Paper rows are never ranked or coloured.
- [DEFERRED] Showing ours-per-sentence in `GoldPanel` (needs projection output in item detail).
- [DEFERRED] Pagination, sort, next/previous item.
- Large saved item slow to open: open the biggest saved item once; no mitigation planned.

## Acceptance Criteria
1. Run detail shows our rows grouped by level and slice with primary and secondary values, n and CI on every row; paper rows greyed with the exact label; failures count and policy note visible.
2. Re-score disables itself, shows "Scoring...", polls, then shows refreshed metrics; stops polling on unmount.
3. Run info shows commit (+dirty), models, prompt hashes, mapping version, seed, cost or "unknown"; test split adds the informational line and nothing else.
4. Item list filters all/mismatch/failed and opens items; ids containing `.`, `-` and `--` open correctly.
5. An ok item renders `GoldPanel` plus `ReviewShell` with no upload button, no network call to the audit service, and remounts cleanly when another item opens.
6. A 1.0.0-schema or invalid saved response shows `ErrorScreen`; a failed item shows error info and no review view; unknown `gold_kind` shows JSON fallback.
7. Compare shows `n shared`, deltas and disagreements; "No shared items" for zero; click-through opens the item and Back returns to the comparison.
8. All fixtures validate against `eval/api/eval-api.schema.json`; `ReviewShell`/`LeftPane`/`RightPane`/`reviewState` diffs are empty; existing Audit tests still pass.
9. Tests (`docs/testing/frontend.md` conventions, injected `fetch`, Testing Library): `MetricsTable`, `RunInfoBlock`, `ItemList`, `GoldPanel` (both renderers), `buildLoadResult` (ok pair from `docs/contracts/examples/`, stale, bad request), `ItemDetail` (ok/failed/stale/fetch error), `RunDetail` (scoring poll), `CompareView`, `Header` without `onFile`; `eval/mock-flow.test.tsx` extended with run -> item -> compare. `npm test`, `npm run typecheck`, `npm run build` pass.
10. Docs updated: `docs/reference/eval-ui.md` (run detail, items, gold kinds, compare), `docs/implementation/frontend.md` (eval section, `buildLoadResult`, Header change), `docs/testing/frontend.md` (new tests, release-checklist item: open one real eval item), `docs/concepts/review-ui.md` (item view is read-only replay); folder READMEs linked.
