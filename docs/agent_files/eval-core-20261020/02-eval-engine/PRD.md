---
status: draft
summary: Root eval/ Python project that selects items from a plug-in dataset, audits them against the running backend over HTTP with schema validation, and stores crash-safe, resumable runs. No scoring, no UI API.
date: 2026-10-20
---
# PRD: 02 Eval engine

Repo/branch: iaudit / `users/codex/eval-investigation` · Depends on: B1 (`run_info` in responses, contract 1.1.0) · Owns: `eval/pyproject.toml`, `eval/uv.lock`, `eval/.gitignore`, `eval/README.md`, `eval/src/iaudit_eval/{paths,contracts,client,store,engine,selection,estimate,download,log}.py`, `eval/src/iaudit_eval/datasets/{base,registry}.py`, `eval/datasets/synthetic/`, `eval/tests/`, `docs/decisions/0008-*.md` (stale-number fix only: 60 s -> 100 s)

## TL;DR
Library only. `select()` picks a seeded sample from any dataset adapter; `engine.run()` sends each item to `POST /v1/audit` (concurrency 4), validates every request and response against `docs/contracts/`, and writes one atomic file per item under gitignored `eval/runs/<run_id>/`. Runs resume (redo failed/missing only), optionally stop at a max-cost cap (unset = no cap), and expose progress through the store. B3 adds scoring, B4 the HTTP API, C1/C2 the first real adapter.

## Problem
No tool evaluates iAudit on external datasets. The ADHD harness (`backend/eval/`) is tied to backend internals and recordings. We need a black-box runner that is dataset-agnostic, cheap to resume after failures, honest about cost when reported, and safe for licensed text. [verified: no root `.gitignore`; `backend/.gitignore` exists; `backend/eval/` untouched by this work]

## Goals / Non-Goals
**Goals**
- Plug-in dataset contract (metadata + adapter protocol) that B3/C implement against.
- Every request validated before send, every response validated on receipt; schemas read from `docs/contracts/`, never copied.
- Crash-safe per-item persistence; resume; cost estimate and optional cap (shown/enforced only from reported `cost_usd`); abort.
- ADR 0008 corrected to the canonical 100 s audit deadline (`config.py` `audit_deadline_s = 100`).
- Download framework with status and hashes.
- Fictional synthetic dataset + tests on a fake backend (zero spend).

**Non-Goals**
- Scoring, metrics, compare, bootstrap (B3). Eval HTTP server, `scripts/dev.sh` (B4). TofuEval (C). UI (D).
- CLI (scrapped). Replay/recordings. Auth, hosting. Adding eval tests to CI (see Risks).
- Importing `iaudit_backend` (boundary rule). Editing `backend/eval/`, `leakage.toml`, or contracts (only the stale ADR 0008 number is edited).

## Requirements
1. **Project**: `eval/` own uv project, name `iaudit-eval`, `requires-python >=3.12,<3.13`, hatchling, package `src/iaudit_eval`. Runtime deps: `httpx`, `jsonschema`, `referencing` (same libraries as backend). Dev: `pytest`, `pytest-asyncio` (`asyncio_mode=auto`), `ruff` (line 100, rules E,F,I,UP,B). Tests run `cd eval && uv run pytest`. [verified: backend pyproject uses these; uv not installed on this machine, so lock generation is unverified here]
2. **Paths** (`paths.py`): repo root = `parents[3]` of the module file (same trick as backend `contract.py`). `IAUDIT_CONTRACTS_DIR` overrides contracts dir; `IAUDIT_EVAL_HOME` overrides the `eval/` dir (runs, data, datasets live under it) so tests use `tmp_path`. Never relative to cwd.
3. **Contracts** (`contracts.py`): load the three schemas with the same `referencing` registry approach as backend `contract.py`; `validate_request/response/error(obj) -> list[Issue]`. Issues carry schema path + keyword wording only, never instance values (PHI). Small reimplementation, not an import. Schema `1.x` acceptance is whatever the files say; no hard-coded version in eval.
4. **Client** (`client.py`): `AuditClient(base_url, timeout_s=120, transport=None)` over `httpx.AsyncClient`. `audit(request) -> Outcome`. Total timeout 120 s (ADR 0008 UI wait) with 5 s connect. Result kinds: `ok` (200 + valid response), or `failed` with `kind` in `timeout | network | http_error | error_body | invalid_request | invalid_response | request_id_mismatch`, plus `http_status`, `error_code`/`message` when the body is a valid ErrorResponse, and `issues`. Non-JSON/invalid error bodies store status only. One automatic retry (2 s backoff) only for connect errors, 429, 502, 503; never for timeouts or 504 (spend may have occurred; resume handles). `attempts` recorded.
5. **Dataset plug-in** (`datasets/`): see Architecture. Discovery scans `eval/datasets/*/metadata.json`; adapter loaded by file path. Registry: `list_datasets()`, `load(name) -> Dataset(meta, adapter)`.
6. **Selection** (`selection.py`): `select(items, n, seed) -> list[Item]`; `split="all"` handled by `Dataset.items("all")` (union of declared splits, de-duplicated by id).
7. **Run store** (`store.py`): see Architecture. All writes atomic.
8. **Engine** (`engine.py`): `estimate`, `start_run`, `resume`, `abort`, state machine, progress; see Architecture.
9. **Download** (`download.py`): generic fetcher for adapter-declared sources.
10. **Synthetic dataset** `eval/datasets/synthetic/` (committed, fictional) with 2 splits, 3 documents, ~8 items; implements all four adapter methods.
11. **Tests** on a fake backend (`httpx.MockTransport`, in-process; builds schema-valid responses incl. `run_info`, with switches for 429, 503, 504, timeout, bad body, mismatched id, missing `cost_usd`).
12. **Logging** (`log.py`): `logging` with an allowlist of fields (run_id, item_id, status, counts, durations, http_status, kind). Never request/response text. Sentinel-word test mirrors backend S9.
13. **Gitignore**: `eval/.gitignore` with `runs/`, `data/`, `.venv/`, `__pycache__/`, `.pytest_cache/`, `.ruff_cache/`, `*.pyc` (no root file; matches the frontend/backend per-project pattern). Runs/data dirs created `0700`, files `0600`.

## Architecture
```
eval/
  datasets/<name>/{metadata.json, adapter.py, ...}   # committed code + metadata only
  data/<name>/            # gitignored: downloads + download.json
  runs/<run_id>/          # gitignored: run.json, run.lock, items/<item_id>.json
  src/iaudit_eval/...
```
Data flow: `Dataset.items(split)` → `select(n, seed)` → run.json written (state `running`) → canary item → fan-out (semaphore = concurrency) → per item `to_request` → validate → POST → validate → atomic write `items/<id>.json` → progress callback → end: recompute totals from item files, state set, `on_finish` hook (B3 attaches scoring).

**Adapter protocol and Item** (defined here; B3 uses `gold`/`project`)
```python
@dataclass(frozen=True)
class Item:
    id: str          # unique in dataset; [A-Za-z0-9._-]{1,128}, used as filename; preflight asserts uniqueness+charset (filename-safe by contract, no escaping layer; C1 slugs its ids)
    doc_id: str      # cluster key (source document) for B3 bootstrap
    split: str
    payload: Mapping # adapter-private; JSON-serialisable
    meta: Mapping    # slice attributes (topic, model, ...); JSON-serialisable
class Adapter(Protocol):
    def items(self, split: str) -> Iterable[Item]
    def to_request(self, item) -> dict      # AuditRequest; request_id optional
    def gold(self, item) -> Any
    def project(self, response: dict, item) -> Any   # may raise Unmapped (class in datasets/base.py; B3 scoring catches it -> failure "unmapped")
    # optional hooks (default: no-op / generic behaviour):
    #   post_download(data_dir: Path) -> None
    #   download(data_dir: Path, progress) -> list[FileRecord]   # replaces the generic fetcher for non-trivial sources (C1); framework still writes download.json
    #   pairs(item, gold, prediction, failure) -> list[Pair]     # B3 R1: multi-level scoring pairs
    #   item_row(item, gold, prediction, failure) -> ItemRow     # B3 R8 writes item_rows.json; B4 serves it
    #   mapping_version() -> str | None                          # recorded in run.json at start (C2)
    #   report_extra(run, runs_root) -> dict                     # B3 R7 `dataset_extra` (C2 integrity block)
```
Discovery: `adapter.py` must expose `def create(data_dir: Path) -> Adapter`; loaded with `importlib.util.spec_from_file_location` under a namespaced module name. Adapters may import `iaudit_eval` only.

**`metadata.json`**
| Field | Type | Note |
|---|---|---|
| `name` | str | = folder name |
| `title`, `description` | str | UI display |
| `dataset_version` | str | goes into run.json; bump when items/gold change |
| `kind` | `"adapter"` | `"custom"` reserved (no-code, later) |
| `splits` | `[{name, description}]` | `"all"` is implicit, never declared |
| `default_split` | str | |
| `cluster_key` | str | human label of `doc_id` (e.g. "source meeting") |
| `license` | `{name, redistributable: bool, contains_licensed_text: bool}` | |
| `data_required` | bool | false for synthetic |
| `sources` | `[{id, url, filename, sha256?, size_bytes?}]` | download framework input |
| `test_split_note` | str? | informational note shown when split is the test split (brief #13) |
| `slices` | `[str]` | keys of `Item.meta` to slice by (B3 reads; was `slice_fields`) |
| `mapping`, `references` | filename? | optional files (C2/B3); `references.json` shape in B3 R8 |
| `levels` | `{name: {labels, positive?}}` | scoring levels; shape owned by B3 R3 |
| `metrics` | `[{name, fn?, level, params?}]` | metric config; omitted = all built-ins (B3 R3) |
| `pool_all` | bool, default true | B3 R4: false = no all-pairs (pooled) entry |
| `gold_kind` | str? | tells the UI how to render `gold` (dataset defines; C2: `tofueval_summary_sentences`); absent = generic JSON |

Unknown keys are preserved and readable by the adapter (C1 uses `adapter_version`, `item_unit`, `expected_sha256`). `cluster_key` is a free-text label of `Item.doc_id`; scoring always clusters on `Item.doc_id`. `sources[]` entries may also carry `license` and `revision`. `B4`'s `DatasetMeta` is this file plus split sizes from `Dataset.split_sizes()`.

**Selection**: sort by `id`, `random.Random(seed).sample(items, n)`, return sorted by `id`; `n=None` or `n>=len` returns all. Item-level sampling. Default seed `0`, always stored in run.json (UI may offer a different seed). Same (dataset_version, split, n, seed) gives the same ids.

**Run store**
- `run_id` = `YYYYMMDDTHHMMSSZ-<dataset>-<6 hex>`.
- `run.json` fields (`store_version: 1`): `run_id, dataset, dataset_version, split, n_requested, seed, item_ids, concurrency, max_cost_usd (null = no cap), tags (optional run-level object, e.g. `{contamination: str}`, from the start-run request, default `{}`), mapping_version (from `adapter.mapping_version()` if defined, else null), backend_url (no secrets), created_at, finished_at, state, git_commit, git_dirty, git_diff_sha256, schema_version (from first valid response), fingerprint {models, prompt_hashes, from first run_info}, mixed (bool), resumes [{at, git_commit, git_dirty, fingerprint, allow_mixed}], warnings [str], totals {ok, failed, missing, partial, input_tokens | null, output_tokens | null, cost_usd | null} (token/cost sums over responses that report them; null when none do)`. B3 later adds `metrics.json` and `item_rows.json` beside it.
- `items/<id>.json`: `{item_id, doc_id, status: ok|failed, attempts, started_at, finished_at, latency_ms, request, response|null, response_status (complete|partial), run_info|null, failure {kind, http_status?, error_code?, message?, issues[]}|null}`. The item file is the source of truth; `run.json` totals are derived and always recomputed from items.
- **Atomic write**: temp file in same dir (`.<name>.tmp`), `flush`+`fsync`, `os.replace`, `fsync` dir. Stale `*.tmp` removed on resume. Single writer per run enforced by `flock` on `run.lock`; the lock vanishes on crash, so "state=running but lock free" is reported as `interrupted` (derived, not stored). `store.effective_state(run_id)` returns the stored state or `interrupted` for that case; B4 and the UI use it, and `resume` accepts it.
- Reads: `list_runs()`, `load_run(id)`, `iter_items(id)`, `progress(id)` (counts from files, cheap).

**Engine**
- `estimate(dataset, selection) -> Estimate{basis: "prior_runs"|"none", n_items, est_input_tokens, est_output_tokens, est_cost_usd|null, rough: true, note}`. Method: from ok items of prior runs of the same dataset that reported them, fit mean `input_tokens/request_chars`, `output_tokens/request_chars`, `cost_usd/request_chars`; apply to selected request chars. Fields no prior response reported stay null (cost is shown only if present). Cold start returns `basis="none"`, nulls and note "run a small N first". No guessed constants (pipeline fans out per claim, so token multiplier is unknown). Always labelled rough. B4 returns this object unchanged (`n_items`, `basis`, `note`, nulls included) and D1 shows `note` when `basis="none"`.
- `start_run(dataset, selection, *, base_url, max_cost_usd=None, tags=None, concurrency=4, on_progress=None, on_finish=None) -> RunHandle`; `resume(run_id, *, max_cost_usd=None, allow_mixed=False, ...) -> RunHandle`. `RunHandle` wraps an `asyncio.Task`: `.run_id`, `.state`, `await .wait()`, `.abort()`. B4 calls `start_run` inside its event loop and keeps handles in a dict; UI polls `store.progress`, so a server restart loses only the handle, not the data.
- **State machine**: `running → finished | aborted_cost | aborted | failed`; `finished|aborted_cost|aborted|failed|interrupted(derived) → running` via `resume` (not for `failed` caused by dataset missing until fixed). `failed` = run-level fatal (dataset files missing, contract load error, canary unsupported version/schema, or a cap is set and a response lacks `cost_usd`). `finished` includes runs with failed items; those are retried by resume.
- **Dispatch**: (1) preflight: dataset ready (download status), contracts load, adapter builds every request and each validates (fails loudly, zero spend, before any POST). (2) Canary: first item alone; catches `unsupported_version`, connection refused, auth, schema mismatch before fan-out, no extra probe spend. (3) Remaining items under `asyncio.Semaphore(concurrency)`; each completes → file write → totals/cost update → callback.
- **Probe** (`probe(base_url) -> ProbeResult{reachable, backend_schema_version?, accepts_version}`, called by B4 before it creates a run): `GET /healthz`, then one POST with the eval's loaded `schema_version` and an intentionally empty body. The backend checks the version before the schema [verified: `backend/src/iaudit_backend/app.py` ~line 175, "# 3. version, before schema validation"], so `unsupported_version` means mismatch and any other 4xx means accepted, with zero LLM spend. The canary below remains the second line of defence.
- **Cost cap** (optional; `max_cost_usd` unset = no cap, no cost handling at all): spent (this invocation) = sum of `run_info.cost_usd`. When `spent >= max_cost_usd` stop dispatching; in-flight items finish (overshoot bounded by concurrency × per-item cost); state `aborted_cost`. Fail closed: if a cap is set and any response (canary first) lacks `run_info.cost_usd`, the run stops dispatching, in-flight items finish, and the run ends `failed` with a clear run-level error (`cost_missing`: cap set but the backend reports no cost). No warn-and-continue.
- **Resume**: redo items whose file is missing or `status=failed`; `ok` items never re-sent. The first new response is compared to run `fingerprint` (models, prompt hashes). Mismatch: **refuse** (`FingerprintChanged`, nothing written) unless `allow_mixed=True`, then `mixed=true` and the change is appended to `resumes`. Git commit/dirty change only adds a `resumes` entry and a warning. Backend `schema_version` change is always refused.
- **Concurrency**: default 4 (accepted by owner, 2026-10-20). Each audit fans out up to `check_concurrency`/`link_concurrency` 20 LLM calls against `llm_max_concurrency` 20 [verified: config.py], so 4 parallel audits can already saturate the backend and lengthen latency toward the deadline (more `partial` replies). Rate limit rejections are items with `kind=http_error, error_code=rate_limited`, retried on resume. Value is a parameter; not auto-tuned.
- **Abort**: `.abort()` stops dispatch, lets in-flight finish (no cancelled-mid-flight spend loss), state `aborted`.
- **Progress**: callback `(RunProgress{run_id,state,done,failed,total,cost_usd})` for in-process use; same numbers from `store.progress()` for out-of-process readers.

**Download** (`download.py`): `download(dataset, *, progress=None)` fetches each source (httpx streaming) to `eval/data/<name>/<filename>.part`, hashes while streaming, `os.replace` on success, runs adapter `post_download`, writes `download.json` `{status: not_downloaded|downloading|ready|failed, files:[{id, filename, sha256, size_bytes, fetched_at}], error?, updated_at}` atomically. If metadata pins `sha256`, a mismatch fails; if not, the hash is recorded (trust on first use) and later runs record it in `run.json` warnings when it changes. `data_required=true` datasets refuse runs unless status is `ready`. Idempotent: ready + hashes match = no-op.

## Decisions
| # | Decision | Choice | Alternatives considered | Why |
|---|---|---|---|---|
| 1 | Python/deps | 3.12, httpx + jsonschema + referencing | `requests`; pydantic models for run files | Same as backend; plain dicts keep schemas as the single source |
| 2 | Contract loader | Small reimplementation, value-free issues | Import backend `contract.py`; shared package | Boundary rule: eval never imports backend; PHI-safe messages |
| 3 | Paths | repo root via `parents[3]`, env overrides, never cwd | cwd-relative | Works from UI server and tests |
| 4 | Adapter discovery | `importlib` by file path, `create(data_dir)` factory | Entry points; plain package import | Dataset folders are data+code, not installed packages |
| 5 | Selection | Item-level seeded sample, default seed 0, stored | Doc-level sampling; random seed per run | Simple, reproducible; clustering handled in B3 CIs |
| 6 | Item file is truth | Totals recomputed from files | Journal/DB; run.json as truth | Crash cannot desync; trivially inspectable |
| 7 | Single-writer lock | `flock` on `run.lock`; `interrupted` derived | Heartbeat field; PID in run.json | Auto-released on crash; blocks double-resume |
| 8 | Resume on changed models/prompts | Refuse unless `allow_mixed` | Warn only; always refuse | A silently mixed run is uninterpretable; override keeps it possible |
| 9 | Preflight | Zero-spend probe (invalid body) for version/reachability, plus canary first item | Dedicated paid probe request; `/healthz` alone | No extra spend; `/healthz` has no version |
| 10 | Cost estimate | From prior-run ratios when reported, else "unknown" | Char-length constant ratio | Pipeline token multiplier unknown; a made-up number misleads |
| 11 | Retries | One retry for connect/429/502/503 only | None; retry timeouts | Timeouts/504 may already have cost money |
| 12 | Timeout | 120 s total | 60 s | ADR 0008 UI wait is 120 s; canonical audit deadline is 100 s (`config.py`, owner decision 2026-10-20) [verified] |
| 16 | Cost cap | Optional; fail closed when cap set and cost missing | Warn and continue; `require_cost` flag | Owner decision 2026-10-20: no budget handling; no silent unenforceable cap |
| 13 | Progress for B4 | `asyncio.Task` handle + store-derived progress | Event bus; subprocess | B4 owns the loop; store survives restarts |
| 14 | Permissions | dirs 0700, files 0600, gitignored | Default umask | Licensed/PHI text at rest |
| 15 | Request id | Engine sets `request_id=<run_id>:<item_id>` if adapter gave none; response echo checked | No id | Contract echoes it; detects mixed-up replies |

## Manual steps
- Owner manual check: real dataset download and live runs against the real backend with provider keys. Agents verify download and engine only with fakes (`httpx.MockTransport`, synthetic dataset); no live calls (see README "Manual (owner) steps").
- Nothing else for B2. (MeetingBank equality check remains an owner task in C. [DEFERRED])

## Risks / Open Questions
- [RESOLVED: not added, owner decision 2026-10-20] `uv run pytest` for `eval/` in PR CI.
- [RESOLVED: owned by C1 (eval-tofueval 01-data-and-items), owner decision 2026-10-20] `leakage.toml` `scored_dirs` (globs relative to `backend/src/iaudit_backend/`: `eval/data`, `eval/private`, `tests/data`) will also scan root `eval/data` (incl. `eval/data/tofueval`); C1 makes the change where real data first exists.
- [RESOLVED: fail closed, no `require_cost`/`cost_known`, owner decision 2026-10-20] Cap set but response lacks `cost_usd`: run fails with a clear error.
- [RESOLVED: R6] Store `git_diff_sha256` of `git diff HEAD` plus dirty flag in run.json.
- [RESOLVED: R3] No guessed estimate; use prior runs, cold start says unknown and recommends a pilot of ~5 items.
- [RESOLVED: 4 accepted, owner decision 2026-10-20] Concurrency 4 vs backend rate limits; `rate_limited` items are retried on resume.
- [RESOLVED: 100 s canonical, owner decision 2026-10-20] Audit deadline: `config.py` `audit_deadline_s = 100` wins; ADR 0008 (title "One synchronous call with a 60 second cap", body 60 s default) is stale and is updated to 100 s within B2 scope (see Owns, AC 15). Eval client timeout 120 s unchanged. C1 and A1 refer here.
- [RESOLVED: metadata keys, `Item.doc_id`, `on_finish`] B3's OPEN-1..4 are answered by the metadata table, the optional adapter hooks and the `on_finish` default (B3 sets `score(run_id)` as the default; B4 passes its own wrapper that tracks `score_state`).
- [RESOLVED: optional run tag] `tags` in run.json is set only via the start-run request (B4 body); default `{}`; D1 has no UI field in v1.
- Partial (`status=partial`) replies are stored `ok` with `response_status=partial`; B3 decides scoring policy. [RESOLVED: B2 stays policy-free]
- Windows lacks `fcntl.flock`; Linux/macOS only (single local user). [RESOLVED: accepted]
- Synthetic text must not share an 8-word window with `prompts/*_fewshot.json` nor use speaker ids `alex1/sam1/clinician1`; a test reads those files by path (read-only, skipped if absent). [RESOLVED]

## Acceptance Criteria
1. `cd eval && uv run pytest && uv run ruff check src tests` pass with no network and no API key.
2. Schemas are read from `docs/contracts/`; grep shows no copy of a schema in `eval/`; `eval` imports nothing from `iaudit_backend`.
3. Synthetic dataset: `items("all")` = union of splits; `select(n=3, seed=0)` is identical across calls and differs from `seed=1`; `n=None` returns all.
4. Fake-backend run of all synthetic items writes one valid item file each and `run.json` totals match; every stored request and response validates against the schemas.
5. A bad adapter request fails preflight with zero POSTs. Invalid response, bad error body, and wrong `request_id` become `failed` items with the right `kind`.
6. Kill the engine mid-run (test simulates by cancelling): no torn files; reload reports `interrupted`; `resume` re-sends only failed/missing items (fake backend request count asserted).
7. Resume with changed model ids refuses; with `allow_mixed=True` records `mixed` and the change.
8. Cap set and exceeded with reported costs: state `aborted_cost`, dispatch stopped, in-flight finished, resumable. Cap set and a response lacks `cost_usd`: run ends `failed` with a clear error (fail closed). No cap (default): missing `cost_usd` is ignored, no warning.
9. `abort()` yields `aborted`; two concurrent resumes of one run: second is refused by the lock.
10. Concurrency never exceeds 4 in flight (fake backend counts).
11. Estimate: prior-run fixture yields labelled rough numbers; cold start returns nulls.
12. Download: fake source served via `MockTransport` ends `ready` with sha256; pinned-hash mismatch ends `failed`; re-run is a no-op; missing data blocks a run.
13. Sentinel word in transcript never appears in captured logs or in validation issue strings.
14. `eval/.gitignore` ignores `runs/` and `data/` (`git check-ignore` verified); run dirs are mode 0700.
15. `docs/decisions/0008-*.md` title and body say a 100 second cap / 100 s default, matching `config.py` `audit_deadline_s = 100`; no other ADR text changed.
