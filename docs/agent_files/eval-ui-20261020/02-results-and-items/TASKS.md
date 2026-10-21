---
status: draft
summary: Eleven tasks: shared-file edits, buildLoadResult, eval API wrappers and fixtures, metrics and run info, item list, run detail, gold panel, item detail, compare, EvalApp wiring, docs.
date: 2026-10-20
---
# Tasks: D2 Results & items

Source of truth: docs/agent_files/eval-ui-20261020/02-results-and-items/PRD.md. Adds run detail, item list, read-only item replay through the unchanged ReviewShell with a gold panel, failed-item view and two-run compare on top of D1. All verification is components, fake-fetch tests and fixtures; real-data and real-browser checks are owner manual checks (closing note).

| # | Task | Depends on | Status |
|---|---|---|---|
| 1 | Shared-file edits: Header, ErrorScreen, response-check helper | none | done |
| 2 | buildLoadResult | 1 | done |
| 3 | Eval API wrappers and schema-validated fixtures | none | done |
| 4 | MetricsTable and RunInfoBlock | 3 | done |
| 5 | ItemList | 3 | done |
| 6 | RunDetail with scoring state and Re-score | 4, 5 | todo |
| 7 | GoldPanel and renderers | none | done |
| 8 | FailedItem and ItemDetail | 1, 2, 3, 7 | done |
| 9 | CompareView | 3 | done |
| 10 | EvalApp view wiring and mock-flow test | 6, 8, 9 | todo |
| 11 | Docs | 10 | todo |

## Task 1 — Shared-file edits: Header, ErrorScreen, response-check helper
What it is / what it means: The three minimal edits to existing audit files that let a saved item reuse the review path (PRD Architecture shared-file table; Decisions D1, D2; R7).
What changes at a high level: Make the Header's file input and upload button optional so they render only when a file handler is passed. Make ErrorScreen's "Choose another file" optional the same way. Extract the post-parse response checks from `auditRequest` into one exported helper that both `auditRequest` and the later `buildLoadResult` call. `ReviewShell`, `LeftPane`, `RightPane`, `reviewState`, `ClaimDetail` are not touched.
Done when: a Header test without the file handler shows no upload control; ErrorScreen test shows no choose-file button when absent; existing Audit tests pass unchanged; diffs to the protected review files are empty.

## Task 2 — buildLoadResult
What it is / what it means: Pure conversion of an already-parsed saved request/response pair into a `LoadResult` (R7; Decisions D2, D4).
What changes at a high level: Add `buildLoadResult(request, response)` returning a `Result`: validate the request, run the shared response checks from Task 1, then analyze the response, with `source: "service"`. No network, no JSON parsing. Errors map to the same load errors as Audit, including `invalid_response/wrong_version` for stale 1.0.0 data.
Done when: tests cover an ok pair from `docs/contracts/examples/`, a stale-version response, an invalid response and a bad request; no fetch is made.

## Task 3 — Eval API wrappers and schema-validated fixtures
What it is / what it means: The data layer and test data for all D2 views (Architecture shared-file row for D1 files; R5, R10; Decision D5; Acceptance 8).
What changes at a high level: Extend D1's `evalApi` with `getMetrics`, `rescore`, `listItems`, `getItem` and `compare`, same never-throw `Result` pattern, item ids passed through `encodeURIComponent`, metrics 404 `not_found` treated as a non-error result. Add fixtures for metrics (primary/secondary, paper references, few-cluster CI), run detail with run_info, item rows, ok and failed item details (including gold), and comparisons (shared, zero shared, cross-dataset 409).
Done when: wrapper tests with injected fetch cover success, 404, 409 and network failure; every fixture validates against `eval/api/eval-api.schema.json`.

## Task 4 — MetricsTable and RunInfoBlock
What it is / what it means: Pure-prop presentation of metrics and provenance (R3, R4; Decision D5; Acceptance 1, 3).
What changes at a high level: Add the `toMetricRows` normalizer as the only code aware of the B3 report shape. MetricsTable groups by level then slice, shows primary and secondary side by side with value, n, CI (dash plus status hint for `few_clusters`/`undefined`, `n_clusters` on hover), the failures line, greyed paper rows with the exact label and collapsed caveats. RunInfoBlock shows commit and dirty flag, models, 8-char prompt hashes with full value in title, mapping version, seed, tags, cost or "unknown", mixed-fingerprint warning, warnings, and the test-split informational line only.
Done when: component tests cover grouping, policy none feeding the failures line, reference rows, CI dash cases, null cost, mixed warning, and the test-split line; paper rows are never ranked or coloured.

## Task 5 — ItemList
What it is / what it means: Filterable table of a run's items (R5; Decision D7; Acceptance 4).
What changes at a high level: Radio filter all | mismatch | failed driving one `listItems` request with a high limit and no paging. Columns Item (`label ?? item_id`), Gold, Ours, Match (check/cross/dash) and a Status chip for failed rows; row click calls `onOpenItem`. Empty state text; table stays visible and dims during a filter reload.
Done when: tests with fake fetch cover each filter, row click, ids containing `.`, `-` and `--`, the empty message and the dimmed-loading state.

## Task 6 — RunDetail with scoring state and Re-score
What it is / what it means: The run page composing title, state chip, failures, metrics, items and run info, with scoring lifecycle (R1, R2, R11; Acceptance 2).
What changes at a high level: Fetch run and metrics; render "Scoring..." in place of the table while `score_state` is pending/running, with Re-score disabled (also disabled while run state is running); poll through D1's `usePolling` until done/failed then refetch metrics. Re-score posts then reuses the polling path; failed score shows a message with Re-score enabled; metrics 404 with done shows "Metrics missing. Re-score."; unreachable server uses D1's banner with Retry and its 3-miss rule.
Done when: tests cover the full scoring poll to refreshed metrics, 409 handling, failed score, missing metrics, banner state, and polling stopping on unmount.

## Task 7 — GoldPanel and renderers
What it is / what it means: Dataset-aware gold display kept out of review components (R9; Decision D9; Acceptance 6).
What changes at a high level: A registry keyed by `gold_kind`, a `TofuEvalGold` renderer for `tofueval_summary_sentences` (index, text, label, native error-type strings, explanation) that guards the shape, and a `GenericGold` collapsed pretty-printed JSON fallback for unknown kinds or shape mismatch. Panel is collapsible with a 30vh scroll cap and never imports from `app/`.
Done when: tests cover both renderers, unknown kind fallback, malformed TofuEval gold fallback, and collapse behaviour.

## Task 8 — FailedItem and ItemDetail
What it is / what it means: The read-only item view branching on load, error, ok, stale and failed (R6, R8; Decisions D3, D4; Acceptance 5, 6).
What changes at a high level: FailedItem shows failure kind, HTTP status, error code, message and up to 50 issues, omitting absent fields, with the "No response was saved. Resume the run to retry." line. ItemDetail fetches the item and renders back bar plus GoldPanel plus either `ReviewShell` keyed by run/item (no upload, header showing run - item), the existing ErrorScreen on `buildLoadResult` failure, or FailedItem; fetch errors give Retry in D1's Result style.
Done when: tests cover ok, failed, stale 1.0.0, invalid, fetch error with Retry, remount when the item changes, no call to the audit service, and no upload control.

## Task 9 — CompareView
What it is / what it means: Two-run comparison with shared-item count and click-through (R10; Decision D8; Acceptance 7).
What changes at a high level: Fetch compare; show run labels, prominent "n shared = k", a delta table (metric, level, slice, A, B, signed delta, delta CI only when `ci_status` ok, no colour judgement) and a disagreements list with per-pair level, unit, gold, A, B and "open in A" / "open in B" actions. Zero shared shows "No shared items"; a 409 across datasets shows an inline error.
Done when: tests cover normal, zero-shared and 409 cases, CI hidden unless ok, and the open-in callbacks passing run and item ids.

## Task 10 — EvalApp view wiring and mock-flow test
What it is / what it means: Connects the new screens into D1's shell (Architecture view union; R6, R10; Acceptance 7, 9).
What changes at a high level: Add the `item` view (with origin run/compare and compare pair) and `compare` view to `EvalApp`; wire RunDetail item clicks, compare entry and the item back button that returns to run detail or "Back to comparison". Extend `eval/mock-flow.test.tsx` through run, item, back, compare, open in A/B and back.
Done when: the extended flow test passes; `npm test`, `npm run typecheck` and `npm run build` pass; protected review file diffs remain empty.

## Task 11 — Docs
What it is / what it means: Documentation required by Acceptance 10.
What changes at a high level: Append run detail, items, gold kinds and compare sections to `docs/reference/eval-ui.md`; add the eval section, `buildLoadResult` and Header change to `docs/implementation/frontend.md`; add the new tests plus a release-checklist item (open one real eval item, owner check) to `docs/testing/frontend.md`; note in `docs/concepts/review-ui.md` that the item view is read-only replay. Link folder READMEs.
Done when: all four docs updated, links resolve, and the stale-after-A1 (`wrong_version`) behaviour is stated.

## Owner manual checks (not tasks)
- Eyeball one real TofuEval item: GoldPanel against the source CSV, after C2 data is downloaded and a paid run exists.
- Open the largest saved item once to confirm acceptable load time.
- After A1 lands, confirm the pre-A1 baseline run's items show the `wrong_version` ErrorScreen while metrics, compare and lists still work.
