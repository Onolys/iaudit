---
status: draft
summary: Dataset-agnostic metrics registry, versioned metrics.json and compare.json schemas, clustered-bootstrap CIs, failure-as-wrong policy, and a pure idempotent scoring step plus run-vs-run compare.
date: 2026-10-20
---
# PRD: 03 Metrics & scoring

Repo/branch: iaudit / `users/codex/eval-investigation` · Depends on: B2 (02-eval-engine) · Consumed by: B4 (eval API), C2 (TofuEval metrics/references), D1/D2 (UI) · Owns: `eval/src/iaudit_eval/metrics/` (`pair.py`, `registry.py`, `builtins.py`, `policy.py`, `bootstrap.py`), `eval/src/iaudit_eval/scoring.py`, `eval/src/iaudit_eval/compare.py`, `eval/schemas/metrics.schema.json`, `eval/schemas/compare.schema.json`, `eval/tests/test_metrics_*.py`, `test_scoring.py`, `test_compare.py`, one-line scoring hook in B2's `engine.py`

## TL;DR
A saved run (B2) becomes a metrics report with no LLM calls. The adapter turns each item into **pairs** (gold, prediction, meta) at one or more **levels** (e.g. sentence, summary). Registered metrics reduce pairs to values. Failures are applied by one generic rule (primary: wrong; secondary: excluded). CIs are source-document-clustered bootstraps on per-cluster sufficient statistics (fast, deterministic). Two runs of one dataset compare on shared items only. Both outputs are JSON Schemas under `eval/schemas/`, which B4 serves and D renders.

## Problem
- B's brief fixes the report shape `{metric,value,n,ci,slice,impl}` but not what a metric receives, how multi-level items (TofuEval sentence + summary from one item) are scored, how failures become "wrong" for non-binary labels, or how CIs stay fast and reproducible.
- Existing `backend/eval/score.py` is ADHD-fixture-specific (buckets, `Counts`) [verified: read `score.py`, `compare.py`]. Only the idea (never one overall number; `n` beside every value) carries over; no code is shared.
- INVESTIGATION 9.1/9.3: native tasks stay visible; failures stay in the denominator; clustered CIs; no pooled headline.

## Goals / Non-Goals
**Goals**
- Registry of named metrics; built-ins `balanced_accuracy`, `precision`, `recall`, `f1`, `recall_by_type`, `failure_rate`, `coverage`; dataset override by same name.
- `metrics.json` and `compare.json` as versioned JSON Schemas; every output validated against them in tests and at write time.
- Pure, idempotent `score(run_id)`; auto at run end; re-score on demand; records scorer git commit.
- Reference rows passed through; compare on shared items with disagreements.

**Non-Goals**
- Dataset-specific metrics, projection, mapping (C2). HTTP endpoints (B4). Rendering (D).
- Non-label gold (counts, spans, correlations): v1 supports label levels only; the stat/finalize contract leaves room, the "wrong" rule would need a per-level extension.
- Cross-dataset headline, ranking, significance tests across runs, multi-way slice crossing.
- Ordering/leaderboard of reference rows.

## Requirements

### R1. Pair and level
```python
@dataclass(frozen=True)
class Pair:
    item_id: str; cluster: str      # cluster = Item.doc_id (metadata cluster_key)
    level: str; unit: str           # unit unique within (item, level); "" for item-level
    gold: Hashable                  # label
    pred: Hashable | None           # None iff failure is set
    failure: str | None             # None = resolved; else item_failed|unmapped|unresolved|adapter-defined
    meta: Mapping[str, Scalar]      # slice keys + tags, copied from the item by the adapter
```
- Scoring builds pairs by calling `adapter.pairs(item, gold, prediction, failure)` if the adapter defines it, else the default: one pair, `level="item"`, `unit=""`. Adapters must emit pairs **from gold even when the item failed** (pred `None`, failure set) so failures stay in the denominator. Flow: scoring calls `adapter.gold(item)`, then `adapter.project(response, item)` for ok items (a raised `Unmapped` becomes failure `unmapped`; a failed item becomes `item_failed`), then `pairs(...)`. Per-unit failures such as C2's `unresolved` are set by the adapter inside `pairs()` (pred `None`). Dataset metrics never see `pred=None`: `policy.py` runs first.
- Multi-level: one item yields pairs at several levels (TofuEval: N sentence pairs + 1 summary pair). Metrics are always computed per level; levels are never pooled.
- Additional measures (e.g. concern agreement) are just more levels with a boolean gold/pred (`concern:Extrinsic`: gold True, pred = any predicted concern in the allowed set). No special mechanism.

### R2. Metric contract and registry
Every metric is additive so bootstrap runs on summed statistics, not on pair lists:
```python
@metric("recall", policy="primary_secondary")        # or policy="none" for failure metrics
class Recall: 
    def stat(pairs: Sequence[Pair], spec: LevelSpec, **params) -> Stats   # Counter or list; combined by sum/concat
    def finalize(stats: Stats, spec: LevelSpec, **params) -> Result       # Result(value: float|None, n: int)
```
- `pairwise(fn)` helper wraps a plain `fn(pairs)->Result` (`stat` = list, `finalize` = fn) for non-additive metrics; slower, still correct.
- `LevelSpec` = `{labels, positive?}` from `metadata.json` `levels`. `n` is the metric's own denominator (positives for recall, resolved pairs for accuracy).
- Built-ins: `balanced_accuracy` (mean per-class recall over classes present in gold; k-ary ok), `precision`/`recall`/`f1` (`positive` from spec or param; `f1` follows `score.py`: 0 when gold positives exist and tp=0, else None), `recall_by_type` (gold-positive pairs with param `tag` in `meta[tag_key]`), `failure_rate` (param `reason` filters), `coverage` = 1 - failure_rate.
- Resolution: dataset module `datasets/<name>/metrics.py` (`METRICS: dict[str, Metric]`) first, then core. Report `impl` = `core` or `dataset:<name>`. No plugin discovery beyond this.
- Entry naming: metadata metric config `{name, fn?, level, params?}`; `name` is what the report shows, `fn` (default `name`) is the registry key. So `bacc_sentence` = `balanced_accuracy` @ `sentence`, and `unresolved_rate` = `failure_rate` with `reason: unresolved`.

### R3. Metadata assumptions (shape owned by B2; B3 adds the keys below)
```json
"cluster_key": "doc_id",
"levels":  {"sentence": {"labels": [false, true], "positive": true}, "summary": {"labels": [false, true], "positive": true}},
"slices":  ["dataset", "topic_category", "model_name"],
"metrics": [{"name": "bacc_sentence", "fn": "balanced_accuracy", "level": "sentence"}],
"references": "references.json"
```
If `metrics` is omitted: every built-in at every declared level (item-level binary default if no `levels`). B2's metadata table now lists `levels`, `metrics`, `slices`, `references`, `gold_kind` and passes unknown keys through [RESOLVED: OPEN-1]. `cluster_key` is a free-text label; clustering always uses `Item.doc_id`. Optional `pool_all` (default true): when false, R4's all-pairs entry is not emitted, so a dataset can forbid pooled headline numbers (C2 sets false).

### R4. Slices
One-way only. For each key in `slices` and each distinct `pair.meta[key]` at the level, emit an entry with `slice: {key: value}`; plus the all-pairs entry (`slice: {}`) unless `pool_all` is false. Crossed views are built by the adapter as derived `meta` keys (C2: `group_dataset`). Pairs lacking the key appear only in the all slice. Adapter fills `meta` from the item (dataset, topic_category, model_name, model group); run-level tags (e.g. TofuEval contamination) come from `run.json` `tags` (B2) and are copied to `metrics.json` `run.tags`; they are not slice dimensions [RESOLVED: OPEN-2]. No suppression of small cells; `n` and `n_clusters` are always shown.

### R5. Failure policy (one generic rule, `policy.py`)
Applied to a pair subset before `stat`, never inside metrics.

| Policy | Failed pair | Metrics |
|---|---|---|
| `primary` | kept; `pred` := `wrong(gold)` | all prediction metrics |
| `secondary` | dropped | all prediction metrics |
| `none` | untouched | `failure_rate`, `coverage` (computed on all pairs) |

`wrong(gold)`: binary level → the other label (a failed gold-positive is a miss/FN, a failed gold-negative is a false alarm/FP); k-ary → a sentinel outside the label set (miss for its gold class, counted as no class's prediction, so it lowers recall but not any precision). Every prediction metric emits both a primary and a secondary entry. Top-level `failures` always lists selected/scored/failed/not-run items and counts by reason, regardless of metrics configured.

Items without a saved result file (aborted or in-progress run) are **not scored and not failures**; they appear as `items.not_run` with `complete=false`. Attempted-and-failed items are failures.

### R6. Bootstrap CIs (`bootstrap.py`)
- Percentile 95% (2.5/97.5, linear interpolation), `resamples=1000`, seed `0`, all recorded in the report.
- Cluster-level resampling within the entry's pair subset: sample `k` clusters with replacement, sum their precomputed per-cluster stats, `finalize`. Cost is O(clusters) per resample; ~500 entries stay in seconds.
- Per-entry RNG = `Random(sha256(f"{seed}|{metric}|{level}|{policy}|{slice}"))`, so values are independent of entry order and of other metrics added later.
- Samples with undefined value (e.g. no gold positives) are skipped; if fewer than 90% are defined, CI is null.
- Tiny n: report `n_clusters` always; `n_clusters < 5` → `ci: null`, `ci_status: "few_clusters"`; value undefined → `value: null`, `ci_status: "undefined"`; otherwise `"ok"`. Cluster-bootstrap CIs on 5–15 clusters are unstable; consumers show `n_clusters` beside the CI (B brief R8).

### R7. `metrics.json` (schema: `eval/schemas/metrics.schema.json`, `schema_version` "1.0.0", independent of the audit contract version)
```json
{ "schema_version": "1.0.0", "run_id": "...", "dataset": "...", "dataset_version": "...",
  "primary_policy": "failures_count_wrong",
  "scored": {"at": "...", "metrics_version": "1.0.0", "git_commit": "...", "git_dirty": false},
  "bootstrap": {"method": "cluster_percentile", "resamples": 1000, "seed": 0, "level": 0.95},
  "run": {"state": "finished", "complete": true, "mapping_version": null, "tags": {}},
  "dataset_extra": {}, "reference_caveats": [],
  "items": {"selected": 0, "scored": 0, "failed": 0, "not_run": 0},
  "failures": {"by_reason": {"item_failed": 0, "unmapped": 0, "unresolved": 0}},
  "entries": [{"metric": "...", "level": "...", "policy": "primary|secondary|none",
               "slice": {}, "value": 0.0, "n": 0, "n_clusters": 0,
               "ci": [0.0, 0.0], "ci_status": "ok", "impl": "core"}],
  "references": [{"source": "...", "label": "...", "metric": "...", "level": "...", "slice": {}, "value": 0.0, "note": "..."}] }
```
`mapping_version` and `tags` are copied from `run.json`. `dataset_extra` is the opaque object from the optional adapter hook `report_extra(run, runs_root)` (C2 puts its integrity block there). `reference_caveats` is the optional `caveats` list of `references.json`.
Deviation from B brief §4.7 (additive, flagged): `slice` holds only dataset dimensions; `level`, `policy`, `n_clusters`, `ci_status` are separate fields so D filters without parsing slices. Placeholder zeros above are shape only.

### R8. Scoring step (`scoring.py`)
- `score(run_id) -> Report`: load `run.json` + item files (B2 store), dataset adapter and data, build pairs, apply policy, compute entries, validate against schema, write `metrics.json` atomically (temp + rename).
- No network, no LLM. Idempotent: re-running yields byte-identical output except `scored.at` (tested). Needs the dataset's gold on disk; missing data → clear error, no partial file.
- Hook: B2's `start_run(on_finish=...)` default becomes `score(run_id)` (one-line edit in `engine.py`, called after the state is set); B4 passes its own `on_finish` wrapping it to track `score_state`; scoring errors never change run state, are logged, and leave the run re-scorable. Also exposed for B4's re-score endpoint.
- `references.json` (dataset-supplied; C2 authors it) = `{rows: [...R7 `references` shape], caveats?: [str]}`; rows are validated and copied verbatim into `references`, caveats into `reference_caveats`.
- Scoring also writes `item_rows.json` (atomic) beside `metrics.json`: one row per scored or failed item from `adapter.item_row(...)`, else the generic row. Common `ItemRow` (defined once, here): `{item_id, label?, status: ok|failed|unmapped, gold: str, pred: str|null, match: true|false|null, outcome?: str, detail?: object}`. `gold`/`pred` are short display strings; `detail` is dataset-private JSON (C2: per-sentence data). No transcript text, no gold text. B4 serves it; the generic row uses the single item-level pair's labels as strings. No `n`, no CI, no policy; D must not rank them.

### R9. Compare (`compare.py`, schema `eval/schemas/compare.schema.json`)
- `compare(run_a, run_b) -> Comparison`. Error if datasets differ; warnings if `dataset_version`/`mapping_version` differ.
- Shared = item ids with a saved result in both runs (ok or failed). Both runs are **re-scored on the intersection** through the same code path (not read from stored `metrics.json`).
- `deltas[]`: per `(metric, level, policy, slice)` present in both: `{a:{value,n,ci}, b:{...}, delta, delta_ci, ci_status}`. `delta_ci` = paired cluster bootstrap (same resampled clusters applied to both runs); null under the R6 rules.
- `disagreements[]`: items where any pair's effective prediction (after primary policy; a failure is `"FAILED"`) differs: `{item_id, cluster, pairs:[{level, unit, gold, a, b}]}` listing only differing pairs. `n_shared`, `n_a_only`, `n_b_only`, `n_clusters_shared` at top. `n_shared = 0` → empty deltas, no error.

## Architecture
```
eval/schemas/{metrics,compare}.schema.json
eval/src/iaudit_eval/
  metrics/pair.py        Pair, LevelSpec, Result, default_pairs
  metrics/registry.py    @metric, resolve(name, dataset) -> (Metric, impl)
  metrics/builtins.py    the seven built-ins
  metrics/policy.py      apply(pairs, spec, policy)
  metrics/bootstrap.py   cluster stats, percentile CI, paired variant
  scoring.py  compare.py
eval/datasets/<name>/metrics.py   optional overrides (C2)
```
Flow: `store -> items -> adapter.gold/project/pairs -> pairs -> [policy] -> per-cluster stat -> sum -> finalize -> entries -> metrics.json`. Compare reuses everything after "items" on the intersection.

## Decisions
| # | Decision | Choice | Alternatives considered | Why |
|---|---|---|---|---|
| 1 | Metric input | `Pair` list with `level`/`unit`/`meta` | Metric takes whole items; adapter computes metrics | Same engine serves sentence+summary, PriMock, custom; slices by meta |
| 2 | Multi-level | Adapter optional `pairs()`; default one item-level pair | Extend `project()` return type | No change to B2's four-method protocol |
| 3 | Metric form | Additive `stat`/`finalize` (+ `pairwise` fallback) | Plain functions only | Plain functions make ~500 bootstraps minutes-slow; counts make them seconds |
| 4 | Wrong rule | Central `policy.py`: flip (binary) / sentinel (k-ary) | Each metric handles failures | Dataset overrides cannot accidentally drop failures |
| 5 | Override | Same name in `datasets/<name>/metrics.py`; `impl` records it | Registry plugins, entry points | YAGNI |
| 6 | Aliases | `name` vs `fn` + `params` in metadata | One function per TofuEval metric | `bacc_sentence`, `unresolved_rate` need no code |
| 7 | Slices | One-way, `meta` keys declared in metadata | Crossed slices; query DSL | Covers TofuEval/PriMock needs; entry count bounded |
| 8 | Bootstrap | Cluster percentile, B=1000, seed 0, per-entry RNG | i.i.d.; BCa; numpy | INVESTIGATION 9.1; stdlib only; order-independent determinism |
| 9 | Tiny n | `n_clusters<5` → null CI + status | Always compute | Misleading intervals are worse than none |
| 10 | Incomplete runs | Not-run items excluded, flagged `complete=false` | Count as failures | A smaller sample is not a failure; resume completes it |
| 11 | Compare | Re-score on intersection + paired delta CI | Subtract stored metrics | Stored reports cover different item sets (seeded N) |
| 12 | Schema home/version | `eval/schemas/`, own semver | `docs/contracts/` | User-locked: lives in eval/; not an audit-API contract |
| 13 | References | Verbatim pass-through, no CI/rank | Compute deltas vs paper | Different model/date; context only |

## Risks / Open Questions
- [RESOLVED: OPEN-1] B2 metadata table lists `levels`, `metrics`, `slices`, `pool_all`, `gold_kind`; `Item` exposes `doc_id`; items are looked up by id via the store.
- [RESOLVED: OPEN-2] Run-level tags: `run.json` `tags` (B2), copied to `metrics.json` `run.tags`; set via the B4 start-run body, default unset.
- [RESOLVED: OPEN-3] Item file `status` is `ok|failed` (B2); the unmapped case is the exception class `Unmapped` from `adapter.project` (B2 `datasets/base.py`).
- [RESOLVED: OPEN-4] B2's `on_finish` hook exists; B3 sets the default (see R8 Hook), B4 overrides it with a wrapper.
- [RESOLVED: additive stats] Bootstrap performance with ~5k sentence pairs.
- [RESOLVED: policy `none` for failure metrics] failure_rate must not depend on the policy it reports.
- [DEFERRED] Non-label gold (PriMock counts), per-level `wrong` extension.
- [RESOLVED: C2's seam questions] `pred=None` never reaches dataset metrics (policy applies first; the adapter's `pairs()` sets failures). Per-item hook = `adapter.item_row` (R8). Compare warns on differing `mapping_version` itself (R9). Crossed slices are derived meta keys (R4). `none`-policy metrics and `pool_all` cover C2's no-pooling rule.
- [DEFERRED] Multiple-comparison / significance statements across runs.

## Acceptance Criteria
- Hand-computed fixtures (3 clusters, binary and 3-class, some failures) match built-in values for primary and secondary; k-ary failed pair lowers recall, not precision.
- Same inputs and seed → identical entries; adding an unrelated metric does not change existing CIs; a golden CI on a 10-cluster fixture is checked in.
- `n_clusters<5` → null CI + `few_clusters`; no gold positives → `value: null`.
- Dataset override by same name wins and reports `impl: "dataset:<name>"`; aliases (`bacc_sentence`) work with no code.
- `score()` twice → identical except `scored.at`; output validates; works on the B2 synthetic dataset with two levels; auto-runs on engine finish; aborted run gives `complete=false` and `not_run` count.
- References appear verbatim with no `ci`/`n`; malformed reference file fails validation loudly.
- Compare: overlapping-subset fixture gives correct `n_shared`, deltas equal re-scoring both on the intersection, disagreements list only differing pairs; different datasets error; zero overlap returns empty.
- No LLM or network call in `scoring.py`/`compare.py` (test with sockets blocked); `backend/eval/` and `docs/contracts/` untouched.
