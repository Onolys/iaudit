---
status: approved
summary: Project B eval core - black-box, dataset-pluggable eval library under root eval/, plus optional run_info (contract 1.1.0) for model/prompt/token/cost reporting.
date: 2026-10-20
---

# Project B: eval core

## 1. TL;DR

Build a new root-level `eval/` Python project that calls the running backend over `POST /v1/audit`, validates every request and response against `docs/contracts/*.schema.json`, stores resumable per-item runs, and scores them with a registry of reusable metrics and per-dataset adapters. First piece: add an optional `run_info` block to AuditResponse (schema 1.0.0 to 1.1.0) so each response reports models, prompt hashes, tokens and cost. The engine is a library; the UI (project D) drives it through a small local eval API server. The existing `backend/eval/` harness is untouched.

## 2. Problem

| Need | Today (verified) | Gap |
|---|---|---|
| Evaluate on researcher-annotated data without re-annotating | `backend/eval/` runs ADHD fixtures in gold/linked/e2e modes (`backend/eval/README.md`); its split is `poc-all`, "a smoke check ... not a generalization estimate" | No external-dataset path (TofuEval first, PriMock later, custom later) |
| Reusable across datasets | Harness is tied to backend internals (modes, recordings) | Needs black-box, dataset-pluggable design |
| Cost / model / prompt provenance per run | `backend/eval/prices.json` holds estimate prices; token usage is in `MetricsCollector` (`llm/types.py`) but not in the response | Response carries no usage; eval cannot sum cost without importing backend |
| Honest reporting | INVESTIGATION sec 9: native tasks stay visible, failures stay in denominator, clustered CIs, no pooled headline | Must be built into the framework |
| Local UI | Frontend is a review UI only | Needs eval API server + proxy (project D builds the UI) |

## 3. Decision log

| # | Decision | Alternative rejected | Why |
|---|---|---|---|
| 1 | New root `eval/` (sibling of `backend/`, `frontend/`), own Python project; `backend/eval/` stays untouched | Extend `backend/eval/` | Keeps nightly CI/ADHD harness working; no coupling to backend internals |
| 2 | Black box over HTTP `POST /v1/audit`; validate every request and response against schemas loaded from `docs/contracts/` | Import backend code; copy schemas | ADR 0001 (schemas are single source, never copied); nothing else shared. Offsets are Unicode code points, so Python `str` indexing is correct |
| 3 | No CLI; run engine is a library driven by UI via a small local eval API server on its own port; frontend dev server proxies `/eval-api`; `scripts/dev.sh` starts backend + eval server + frontend | CLI-first; eval endpoints inside backend | One driver path to maintain; backend stays product-only |
| 4 | Contract 1.0.0 to 1.1.0: optional `run_info` in AuditResponse (model id per tier, prompt hashes, input_tokens, output_tokens, cost_usd; backend computes cost from its price table) | Separate `GET /v1/info`; HTTP headers; estimate cost from text length | Per-response data belongs in the response; headers/endpoints are outside the schema; text-length estimates are inaccurate. Old responses stay valid; frontend gets it via `@contracts` |
| 5 | Dataset plug-in folder `eval/datasets/<name>/`: `metadata.json`, adapter (`items(split)`, `to_request`, `gold`, `project`), optional `mapping.json` (versioned crosswalk), optional `references.json` (paper numbers as greyed rows); conversion may go ours-to-theirs, theirs-to-ours, or identity; later a no-code "custom" kind (request files + expected responses) | One hard-coded evaluator per dataset; single fixed conversion direction | Per-dataset customization with a shared engine |
| 6 | `eval/metrics/` registry of named metrics; dataset may override a name; report = list of `{metric, value, n, ci, slice, impl}`; CIs by bootstrap clustered by source document; no cross-dataset headline | Per-dataset ad-hoc metrics; i.i.d. bootstrap; pooled score | Reuse; topics/models of one source are correlated (INVESTIGATION 9.1); unlike targets must not be pooled |
| 7 | Selection: split dropdown (incl. "all") + optional N (blank = whole split); seeded random; seed stored | Always full split; unseeded sampling | Cheap partial runs, reproducible |
| 8 | Runs in `eval/runs/` (gitignored); per-item request/response/run_info saved on completion; resumable; concurrency 4; cost estimate before start; max-cost abort; always live | Replay/recordings; in-memory runs | Resume after failure; no stale recordings (ADR 0013 replay is for CI, not this tool); git commit + dirty flag pins code that prompt hashes do not cover |
| 9 | Scoring is a separate step on saved runs (no LLM calls); runs automatically at run end; re-score on demand | Score inline during calling | Metric code changes must not need new spend |
| 10 | Failures (timeout, schema error, unmapped) count wrong in primary score; secondary score excludes them; failure count always reported | Drop failures | INVESTIGATION 9.3: never remove failures from denominator silently |
| 11 | Compare two runs of the same dataset: deltas on shared items only + list of disagreeing items | Compare full sets | Avoids selection bias between different samples |
| 12 | Data in `eval/data/<dataset>/` (gitignored), fetched by a UI Download button using adapter-declared sources; licensed data never committed, never used as prompt examples | Commit data; manual download | License and leakage safety |
| 13 | Test split shows informational note: test runs are for reporting, not tuning; no few-shot/tuning from test | Hard block / confirmation | Matches INVESTIGATION 9.1 leakage policy without friction |
| 14 | Scrapped: Haiku baseline run, system dropdown | Build now | Too complex for now |
| 15 | Out of scope: auth/hosting; adding new eval to CI; cross-dataset headline; pipeline changes beyond `run_info`; PriMock adapter now (interface ready) | Include | Scope control; mission.md |

## 4. Design

### 4.1 Parts and boundaries

| Part | Responsibility | Talks to |
|---|---|---|
| `run_info` (backend + contract) | Emit usage/provenance in response | Contract schema, backend pipeline |
| eval library | datasets, engine, store, scoring, compare | Backend over HTTP only; `docs/contracts/` read-only |
| eval API server | Thin HTTP layer over the library for UI (datasets, download, start/resume run, progress, score, compare) | Library; UI via `/eval-api` proxy |
| Frontend (project D) | UI | Eval API only |

Boundary rules: eval never imports `iaudit_backend`; never copies schemas; backend never reads `eval/`.

### 4.2 Control and data flow

| Step | Action |
|---|---|
| 1 | UI picks dataset, split, N, seed; eval API returns cost estimate (needs prior token averages; see risk R3) |
| 2 | Engine selects items (seeded), writes `run.json`, then per item (concurrency 4): `to_request` -> validate vs request schema -> POST -> validate response (or error schema) -> write `items/<id>.json` immediately |
| 3 | Running cost summed from `run_info.cost_usd`; abort if above max-cost |
| 4 | On finish: score step: `project(response, item)` vs `gold(item)` -> metrics registry -> `metrics.json` |
| 5 | Resume: re-run only items missing or failed. Re-score any time. Compare two runs |

### 4.3 Folder layout

```
eval/
  pyproject.toml
  src/iaudit_eval/
    contracts.py        # load+validate schemas from docs/contracts (path via env/default)
    client.py           # async HTTP client for /v1/audit
    engine.py           # selection, concurrency, cost guard, resume
    store.py            # run folder read/write
    scoring.py          # run -> metrics report
    compare.py
    datasets/base.py    # Adapter protocol, metadata loader
    metrics/            # registry + built-ins
    server.py           # eval API
  datasets/<name>/{metadata.json, adapter.py, mapping.json?, references.json?}
  data/<dataset>/       # gitignored
  runs/                 # gitignored
  tests/
scripts/dev.sh
```

### 4.4 Interfaces (sketch)

```python
class Adapter(Protocol):
    def items(self, split: str) -> Iterable[Item]: ...        # Item has id, doc_id (cluster key)
    def to_request(self, item: Item) -> dict: ...             # AuditRequest JSON
    def gold(self, item: Item) -> Any: ...                    # native labels (or ours if converted)
    def project(self, response: dict, item: Item) -> Any: ... # native-format prediction

Metric = Callable[[list[Pair]], MetricResult]  # registered by name; dataset override by same name
def select(items, split, n: int | None, seed: int) -> list[Item]
async def run(dataset, selection, *, max_cost: float, concurrency: int = 4) -> RunId
def score(run_id) -> Report
def compare(run_a, run_b) -> Comparison
```

### 4.5 Run folder and `run.json`

`eval/runs/<run_id>/{run.json, items/<item_id>.json, metrics.json}`; each item file = `{request, response | error, run_info, status, latency_ms}`.

| `run.json` field | Note |
|---|---|
| run_id, created_at, finished_at | timestamps |
| dataset, dataset_version, split, n_requested, seed, item_ids | selection |
| schema_version | from response |
| git_commit, git_dirty | automatic; covers scoring code not in prompt hashes |
| mapping_version | from `mapping.json`, if any |
| models, prompt_hashes | from first `run_info` seen (check they agree across items) |
| concurrency, max_cost_usd | settings |
| totals: input_tokens, output_tokens, cost_usd, failures | summed from `run_info` |
| state | running / finished / aborted_cost / failed |

### 4.6 `run_info` (contract 1.1.0) sketch

Optional object; field names beyond those listed in decision 4 are open for dev-design.

```json
"run_info": {
  "models": {"cheap": "...", "mid": "...", "strong": "..."},
  "prompt_hashes": {"atomize": "sha256:...", "link": "sha256:...", "check": "sha256:..."},
  "input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0
}
```

Verified anchors: model ids in `backend/src/iaudit_backend/config.py` (`model_cheap/mid/strong`); prompts in `backend/src/iaudit_backend/prompts/{atomize,link,check}_system.md` plus `*_fewshot.json`; usage in `llm/types.py` (`Usage`, `MetricsCollector`); price table currently `backend/eval/prices.json` (estimates; backend would need its own copy or shared location - open, R4).

### 4.7 Metrics report shape

```json
{
  "run_id": "...", "dataset": "...", "primary_policy": "failures_count_wrong",
  "entries": [
    {"metric": "balanced_accuracy", "value": 0.0, "n": 0, "ci": [0.0, 0.0],
     "slice": {"level": "summary", "topic": null, "subset": "all"},
     "impl": "core"},
    {"metric": "balanced_accuracy", "value": 0.0, "n": 0, "ci": [0.0, 0.0],
     "slice": {"level": "summary", "subset": "excluding_failures"}, "impl": "core"},
    {"metric": "failure_rate", "value": 0.0, "n": 0, "ci": null, "slice": {}, "impl": "core"}
  ],
  "references": [{"source": "paper", "metric": "...", "value": 0.0, "note": "greyed"}]
}
```

`impl` names the implementation (e.g. `core` or `dataset:<name>`). Placeholders are 0, not data.

### 4.8 Failure modes

| Failure | Handling |
|---|---|
| HTTP timeout / 5xx | item `status=failed`, retained, retried on resume; counts wrong in primary |
| Request fails schema (adapter bug) | item failed before sending; surfaced loudly (no spend) |
| Response fails schema / error body | failed with schema issues recorded |
| Unmapped item (`project` cannot map) | failed-unmapped; counted wrong |
| Cost above max-cost | stop dispatch, in-flight finish, state `aborted_cost`, resumable |
| Eval server killed mid-run | per-item files survive; resume |
| Response lacks `run_info` (old backend) | cost unknown shown explicitly; max-cost guard cannot enforce - warn |
| Backend schema version mismatch | fail fast at run start via a probe request |
| Dataset files missing | UI Download; run refuses to start |

### 4.9 How verified

| Check | Method |
|---|---|
| Contract 1.1.0 | schema tests: old examples (`docs/contracts/examples/`) still valid; new example with `run_info` valid; update contracts README + both schemas + backend `SUPPORTED_VERSION`/models together |
| Engine | tests against a fake HTTP backend (no spend): resume, concurrency, cost abort, failure accounting |
| Scoring | hand-computed fixtures; bootstrap CI determinism with fixed seed |
| Adapter protocol | tiny in-repo synthetic dataset (fictional) exercising all four methods |
| End-to-end | one small live run (few items) once C exists |

## 5. Non-goals

| Not doing | Reason |
|---|---|
| CLI | decision 3 |
| Replay/recorded eval | ADR 0013 covers CI; this tool is live only |
| Changing `backend/eval/` or CI | decision 1, 15 |
| TofuEval adapter, UI, taxonomy | projects C, D, A |
| Pipeline/prompt changes beyond `run_info` | decision 15, mission scope |
| Auth, hosting, multi-user | decision 15 |
| Headline cross-dataset score | decision 6 |
| Haiku baseline, system dropdown | decision 14 |

## 6. Open risks

| # | Risk | Cheapest test |
|---|---|---|
| R1 | Version bump scope: backend rejects any `schema_version` other than 1.0.0 (`app.py` `SUPPORTED_VERSION`, `models/audit.py` `Literal["1.0.0"]`; contract README says consumers must reject other values), and request schema also carries a version. Does the request stay 1.0.0 while response becomes 1.1.0, or both bump? Unresolved | Read request schema const; list every `1.0.0` occurrence (grep) and decide in dev-design |
| R2 | Frontend/backend must both accept 1.1.0 together; stale frontend rejects new responses | Run frontend tests against example response with `run_info` |
| R3 | Pre-run cost estimate needs tokens per item before any call | Estimate from char length x ratio, label "rough"; compare with actual on a 5-item run |
| R4 | Backend price table location: `backend/eval/prices.json` is eval-side and "estimates"; backend needs its own source for `cost_usd` | Decide in dev-design; cheapest: move/copy to backend config with test |
| R5 | `run_info` tokens aggregate across stages and retries; cache tokens exist (`cache_read_tokens`) and cost semantics unverified | Compare summed `MetricsCollector.records` to `run_info` on a fixture |
| R6 | Git dirty flag does not capture uncommitted diff content | Store `git diff` hash alongside flag (unverified need) |
| R7 | Concurrency 4 vs backend `llm_max_concurrency` (20, verified in config.py) and provider rate limits | 20-item run, watch 429s |
| R8 | Clustered bootstrap with few clusters (e.g. 30 test docs) gives wide/unstable CIs | Report `n_clusters`; sanity-check on synthetic data |
| R9 | Large datasets inflate `eval/runs/` | Report disk size in UI; gitignore verified to be added (no root `.gitignore` found in this check - unverified how ignores are managed) |
| R10 | Proxy/ports collide in `scripts/dev.sh` | Start all three on a clean machine |

## 7. Related projects & links

| Project | Link |
|---|---|
| C: eval-tofueval | [../eval-tofueval-20261020/brainstorming.md](../eval-tofueval-20261020/brainstorming.md) |
| D: eval-ui | [../eval-ui-20261020/brainstorming.md](../eval-ui-20261020/brainstorming.md) |
| A: taxonomy-v1 | [../taxonomy-v1-20261020/brainstorming.md](../taxonomy-v1-20261020/brainstorming.md) |
| Investigation (sec 5, 9) | [../users-codex-eval-investigation-20261020-035707/INVESTIGATION.md](../users-codex-eval-investigation-20261020-035707/INVESTIGATION.md) |
| Mission | [../../mission.md](../../mission.md) |
| Contract docs / ADRs | [../../contracts/README.md](../../contracts/README.md), [0001](../../decisions/0001-frontend-owns-the-contract.md), [0013](../../decisions/0013-recorded-replay-in-ci.md) |

Order: B -> C -> D -> A. Sibling folders may not exist yet.
