---
status: draft
summary: Ten tasks for the pair/metric registry, failure policy, built-ins, clustered bootstrap, metrics and compare schemas, idempotent scoring, engine hook and run-vs-run compare.
date: 2026-10-20
---
# Tasks: 03 Metrics & scoring

Source of truth: [PRD.md](PRD.md). Turns a saved B2 run into `metrics.json` and `item_rows.json` with no LLM or network call, and compares two runs of one dataset on shared items. All tests run offline on hand-built fixtures and B2's synthetic dataset.

| # | Task | Depends on | Status |
|---|---|---|---|
| 1 | Pair, level and result types | none | done |
| 2 | Metric registry, aliases and dataset override | 1 | done |
| 3 | Failure policy | 1 | done |
| 4 | Built-in metrics | 2, 3 | done |
| 5 | Clustered bootstrap CIs | 2 | done |
| 6 | `metrics.schema.json` and `ItemRow` | 1 | done |
| 7 | Scoring step | 4, 5, 6 | done |
| 8 | Auto-score hook in engine | 7 | done |
| 9 | Compare schema and `compare()` | 7 | done |
| 10 | Offline and scope guard tests | 8, 9 | done |

## Task 1 — Pair, level and result types
What it is / what it means: The dataset-agnostic input every metric receives (R1, R3, D1, D2).
What changes at a high level: Add the frozen `Pair`, `LevelSpec` (labels, optional positive) and `Result` types, plus the default pair builder (one item-level pair, empty unit). Add the metadata keys B3 reads (`cluster_key`, `levels`, `slices`, `metrics` entries with `name`/`fn`/`level`/`params`, `references`, `pool_all`) with defaults: all built-ins at every level, item-level binary if no `levels`. Clustering always uses `Item.doc_id`.
Done when: tests cover pair immutability, default pair building and metadata defaulting.

## Task 2 — Metric registry, aliases and dataset override
What it is / what it means: Named, additive metrics resolved with dataset override (R2, D3, D5, D6).
What changes at a high level: A `@metric` decorator with the `stat`/`finalize` contract, a `pairwise` wrapper for non-additive functions, and `resolve(name, dataset)` that checks `datasets/<name>/metrics.py` `METRICS` first, then core, returning the implementation and `impl` (`core` or `dataset:<name>`). Entry naming: `name` is reported, `fn` is the registry key, `params` pass through. No plugin discovery.
Done when: a same-name dataset override wins and reports `dataset:<name>`; an alias such as `bacc_sentence` works with no new code.

## Task 3 — Failure policy
What it is / what it means: The one generic rule for failures, applied before any metric (R5, D4).
What changes at a high level: `policy.py` applies `primary` (failed pair kept, pred set to `wrong(gold)`: other label for binary, out-of-set sentinel for k-ary), `secondary` (dropped) or `none` (untouched). Dataset metrics never see `pred=None`.
Done when: tests show a binary failed positive becomes a miss and a failed negative a false alarm, and a k-ary failed pair lowers recall but not any precision.

## Task 4 — Built-in metrics
What it is / what it means: The seven standard metrics (R2).
What changes at a high level: Implement `balanced_accuracy` (classes present in gold, k-ary ok), `precision`, `recall`, `f1` (0 when gold positives exist and tp=0, else None), `recall_by_type` (by `tag` param over a meta key), `failure_rate` (optional `reason` param, policy `none`) and `coverage` (1 minus failure rate). `n` is each metric's own denominator.
Done when: hand-computed fixtures (3 clusters, binary and 3-class, some failures) match for primary and secondary policy.

## Task 5 — Clustered bootstrap CIs
What it is / what it means: Fast, deterministic uncertainty on summed per-cluster stats (R6, D8, D9).
What changes at a high level: Stdlib-only percentile 95% CI: 1000 resamples, seed 0, cluster resampling over precomputed per-cluster stats, per-entry RNG seeded from a hash of seed, metric, level, policy and slice. Skip undefined samples, null the CI below 90% defined. `n_clusters<5` gives null CI with `few_clusters`; undefined value gives `undefined`; else `ok`. Include the paired variant for compare.
Done when: reruns are identical, adding an unrelated metric leaves existing CIs unchanged, and a golden CI on a checked-in 10-cluster fixture matches.

## Task 6 — `metrics.schema.json` and `ItemRow`
What it is / what it means: The versioned report contract B4 serves and D renders (R7, R8, D12).
What changes at a high level: Author `eval/schemas/metrics.schema.json` (`schema_version` 1.0.0) covering run info, scored block with git commit, bootstrap block, items and failure counts, entries with separate `level`/`policy`/`n_clusters`/`ci_status`, `dataset_extra`, `reference_caveats` and reference rows without `ci`/`n`. Define the common `ItemRow` shape once, with a schema for `item_rows.json`. Add a validation helper.
Done when: valid sample reports and rows pass; malformed ones, including bad reference rows, fail loudly.

## Task 7 — Scoring step
What it is / what it means: Pure, idempotent `score(run_id)` (R3, R4, R5, R8, D10, D13).
What changes at a high level: Load `run.json`, item files and the adapter and gold; call `gold`, `project` (an `Unmapped` raise becomes `unmapped`, a failed item becomes `item_failed`), then `pairs`. Emit one-way slice entries plus the all entry unless `pool_all` is false, with primary and secondary entries per prediction metric. Fill the failures block, count not-run items with `complete=false` (not failures), copy `run.tags` and `mapping_version`, call optional `report_extra`, pass `references.json` through verbatim, and record scorer git commit. Write `metrics.json` and `item_rows.json` atomically after schema validation; missing gold gives a clear error and no partial file.
Done when: scoring the B2 synthetic two-level dataset twice is identical except `scored.at`; an aborted run reports `not_run` and `complete=false`.

## Task 8 — Auto-score hook in engine
What it is / what it means: Scoring runs when a run ends (R8 Hook, OPEN-4).
What changes at a high level: Make B2's `start_run(on_finish=...)` default call `score(run_id)` after the state is set. Scoring errors are logged, never change run state, and leave the run re-scorable. B4's wrapper can still override.
Done when: a finished synthetic run produces `metrics.json` automatically, and a forced scoring error leaves run state unchanged.

## Task 9 — Compare schema and `compare()`
What it is / what it means: Run-vs-run view on shared items (R9, D11).
What changes at a high level: Author `eval/schemas/compare.schema.json` and implement `compare(run_a, run_b)`: error on differing datasets, warnings on differing dataset or mapping version, shared set = items with a saved result in both, both runs re-scored on the intersection through the Task 7 path. Emit `deltas` with a paired-bootstrap `delta_ci`, `disagreements` listing only differing pairs (failure shown as `FAILED`), and the shared/only counts. Zero overlap returns empty deltas.
Done when: an overlapping-subset fixture gives correct counts, deltas equal re-scoring both on the intersection, and output validates.

## Task 10 — Offline and scope guard tests
What it is / what it means: Enforces the PRD's no-network and untouched-areas criteria.
What changes at a high level: Add tests running `score` and `compare` with sockets blocked, and a check that `backend/eval/` and `docs/contracts/` are unchanged by this sub-project.
Done when: both guards pass in the offline suite.

Owner checks (not tasks): none required; scoring a real run is covered by later TofuEval sub-projects.
