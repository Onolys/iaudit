---
status: draft
summary: Local FastAPI eval server (127.0.0.1:8100) over the eval library, the only interface the UI uses, with a committed JSON Schema for every response, plus scripts/dev.sh to start backend + eval server + frontend.
date: 2026-10-20
---
# PRD: 04 Eval API server + dev script

Repo/branch: iaudit / `users/codex/eval-investigation` · Depends on: B2 (engine, store, adapters, downloads), B3 (scoring, metrics report, compare) · Owns: `eval/src/iaudit_eval/server/`, `eval/api/eval-api.schema.json`, `eval/tests/api/`, `scripts/dev.sh`, `scripts/README.md`, `docs/reference/eval-api.md`, `docs/implementation/eval-server.md`

## TL;DR
A thin HTTP layer over B2/B3: datasets, downloads, estimate, start/abort/resume, progress, runs, metrics, items, item detail, rescore, compare. Runs and downloads execute as asyncio tasks inside the server (tab close does not kill a run); one run at a time; runs left `running` after a restart become `interrupted` and are resumable. Responses are defined by pydantic models exported to a committed JSON Schema that D's fixtures validate against. `scripts/dev.sh` starts all three processes with correct env and clean Ctrl-C shutdown.

## Problem
D's UI needs a stable, testable server contract before D is built (D brief §5.4 is "proposals, not verified"). Nothing starts the three processes together; ports and env must line up (frontend audit URL, Vite proxy, eval server's backend URL) or the dev loop breaks (B risk R10).

## Goals / Non-Goals
**Goals**
- Finalize D §5.4 into one endpoint table + schema; D codes against fixtures, not guesses.
- Safe by default: localhost bind, cross-origin POSTs cannot spend money, no transcript text in logs.
- One command: `scripts/dev.sh`.

**Non-Goals**
- Engine, scoring, adapters, download logic (B2/B3/C). CLI (locked). Auth, hosting, HTTPS. SSE/WebSocket. Multiple concurrent runs. Editing gold or items. Any `backend/` change.

## Requirements
1. **Framework**: FastAPI + uvicorn, same as backend [verified: `backend/pyproject.toml` deps `fastapi>=0.115`, `uvicorn>=0.30`; `app.py` is a FastAPI app with `create_app()` factory and lifespan]. Eval `pyproject.toml` (B2-created) gains `fastapi`, `uvicorn`; tests use `httpx` + pytest-asyncio like backend.
2. **Port/bind**: `127.0.0.1:8100` (env `IAUDIT_EVAL_PORT`). Backend defaults to 8000, Vite to 5173 [verified: `backend/README.md` uvicorn `--port 8000`; `config.py` `cors_origins=["http://localhost:5173"]`; no `server.port` in `vite.config.ts`]. Backend URL for the engine: env `IAUDIT_BACKEND_URL`, default `http://127.0.0.1:8000`.
3. **Routes** served at root; the Vite proxy (D1) strips the `/eval-api` prefix (`rewrite`). See table.
4. **Background work**: `RunManager` owns at most one engine task and per-dataset download tasks; blocking I/O via `asyncio.to_thread`.
5. **Errors**: uniform body, below.
6. **Safety**: Host-header and Origin checks, id validation, PHI-safe logging, below.
7. **Schema**: `eval/api/eval-api.schema.json` generated from the pydantic models by `python -m iaudit_eval.server.export_schema`; a test fails if the committed file is stale. It bundles B3's `metrics.schema.json` and `compare.schema.json` into `$defs` (`MetricsReport`, `Comparison`) and a test asserts the bundled copies equal `eval/schemas/*`, so D (Ajv) loads one file.
8. **Dev script**, **docs**, **tests** as below.

### Endpoints
| Method + path | Request | Response (schema `$defs` name) |
|---|---|---|
| `GET /health` | - | `Health` `{status, eval_api_version, backend:{url, reachable, schema_version?}}` (probes backend `/healthz` [verified: `app.py`]) |
| `GET /datasets` | - | `DatasetSummary[]` `{name, title, data_present, splits[{name, size\|null}]}` |
| `GET /datasets/{name}` | - | `DatasetMeta` = B2 `metadata.json` fields (`title`, `description`, `license`, `gold_kind`, `test_split_note`, `default_split`, `splits[{name, description, size\|null}]`); `size` from B2 `Dataset.split_sizes()`, null when data absent |
| `POST /datasets/{name}/download` | - | 202 `DownloadStatus` |
| `GET /datasets/{name}/download` | - | `DownloadStatus` `{status: not_downloaded\|downloading\|ready\|failed (B2 enum), error?, files?}` |
| `POST /runs/estimate` | `{dataset, split, n?, seed?}` | `Estimate` = B2 `Estimate` unchanged `{basis: "prior_runs"\|"none", n_items, est_input_tokens, est_output_tokens, est_cost_usd: number\|null, rough: true, note}` (cost/token fields are null unless prior runs reported them; UI shows cost only if present) |
| `POST /runs` | `{dataset, split, n?, seed?, max_cost_usd?, tags?}` (`max_cost_usd` optional, default unset = no cap; if set and a response lacks `cost_usd` the run fails closed, state `failed`; `tags` e.g. `{contamination: str}`, optional, default unset; D1 has no UI field in v1) | 202 `{run_id}` |
| `GET /runs` | - | `RunSummary[]`, newest first |
| `GET /runs/{id}` | - | `RunDetail` = `RunSummary` + `progress` + `run_info` (run.json fields: git_commit, git_dirty, fingerprint models + prompt_hashes, mapping_version, seed, concurrency, max_cost_usd, tags, mixed, warnings) |
| `POST /runs/{id}/abort` | - | `RunSummary` (state `aborted`) |
| `POST /runs/{id}/resume` | - | `RunSummary` (state `running`) |
| `GET /runs/{id}/metrics` | - | B3 `MetricsReport` (`metrics.schema.json` bundled into `$defs`) |
| `GET /runs/{id}/items?filter=all\|mismatch\|failed&limit&offset` | - | `ItemPage` `{total, items: ItemRow[]}` (`ItemRow` = B3 R8, read from `item_rows.json`) |
| `GET /runs/{id}/items/{item_id}` | - | `ItemDetail` `{item_id, status, request, response\|null, failure\|null, run_info\|null, gold, gold_kind}` (`failure` = B2 item `failure` verbatim; `gold` = `adapter.gold(item)` computed on demand, never persisted) |
| `POST /runs/{id}/rescore` | - | 202 `RunSummary` |
| `GET /compare?a=&b=` | - | B3 `Comparison` (`compare.schema.json` bundled; `n_shared`, `deltas[]`, `disagreements[]`) |

- `RunSummary`: `{run_id, dataset, split, n_requested, n_items, seed, created_at, finished_at?, schema_version, state, score_state, totals:{cost_usd: number\|null, failures}, git_dirty}`.
- `state` ∈ `running | finished | aborted | aborted_cost | interrupted | failed`. `score_state` ∈ `pending | running | done | failed` (drives D's "Scoring..." spinner). B2 stores `running|finished|aborted_cost|aborted|failed` and derives `interrupted` (running with no live lock) via `store.effective_state`; the API reports the effective state and B4 writes no new states. `score_state` is `done` when `metrics.json` exists, otherwise tracked in memory by `RunManager` (`failed` after a scoring exception).
- `progress`: `{done, total, failures, cost_usd: number|null}`; `cost_usd` is `null` when responses lack `cost_usd` (optional per locked decision; the backend does not populate it).
- `ItemRow`: defined once in B3 R8 (`{item_id, label?, status, gold, pred, match, outcome?, detail?}`) and written at scoring as `item_rows.json` using the adapter's `item_row` hook (C2 for TofuEval). Before scoring finishes, or for runs never scored, B4 builds the generic row from item files (`gold`/`pred`/`match` null). `ItemDetail.gold` is opaque JSON typed by `gold_kind` (C2 defines `tofueval_summary_sentences`; D2's GoldPanel switches on it). Filter `failed` = `status == "failed"`; `mismatch` = `match == false`.
- Resume allowed from `aborted`, `aborted_cost`, `interrupted`, `failed`, and `finished` with failures. Rescore refused while `running`. Compare refused across datasets.

## Architecture
```
eval/src/iaudit_eval/server/
  app.py          create_app(settings, backend_client=None, runs_root, datasets_root)  # DI for tests
  models.py       pydantic response/request models (source of eval-api.schema.json)
  routes_*.py     datasets, runs, items, compare   (no business logic)
  manager.py      RunManager: single engine task, downloads, startup sweep, shutdown
  guards.py       id validation, Host/Origin check, error handlers
  export_schema.py
eval/api/eval-api.schema.json   # {$defs: {...}, "x-routes": {"GET /runs": "RunSummary[]", ...}}
```
- **Run lifecycle**: `POST /runs` validates input, checks data present, calls B2 `probe()` (schema-version check against the backend), writes `run.json`, spawns the engine task, returns 202. State is read from the in-memory run if active, else from files. Engine writes item files as they complete; on finish `RunManager` chains B3 `score()` (`score_state` pending→running→done).
- **One run at a time**: second start/resume while one is active returns 409 `run_active` with the active `run_id`. Downloads are independent of runs and limited to one per dataset.
- **Restart**: lifespan startup needs no marking (B2 reports `running` runs without a live lock as `interrupted`); it only resets any in-memory `score_state: running` to `pending`. Lifespan shutdown (SIGINT/SIGTERM) cancels the task, lets in-flight items finish up to a short grace period, then releases the lock, so the run reads as `interrupted`. Unfinished items have no file, so resume redoes them.
- **Errors**: HTTP status + body `{ "error": { "code", "message", "detail?" } }`. Own schema (the audit error enum is closed [verified: `error-response.schema.json`]).

| Code | HTTP | When |
|---|---|---|
| `invalid_request` | 422 | bad body/params, n < 1, unknown split |
| `not_found` | 404 | dataset, run, item, metrics not yet written |
| `run_active` | 409 | start/resume while a run is active |
| `bad_state` | 409 | rescore while running, resume of finished-clean run |
| `data_missing` | 409 | dataset files absent (UI shows Download) |
| `backend_unreachable` | 502 | backend `/healthz` or probe fails to connect/times out |
| `schema_mismatch` | 409 | probe: backend rejects or returns another `schema_version`; `detail` lists both versions |
| `forbidden` | 403 | bad Host/Origin |
| `internal_error` | 500 | fixed message only, never exception text |

- **Security**: (a) bind 127.0.0.1 only; refuse any other `--host` unless `IAUDIT_EVAL_ALLOW_REMOTE=1`. (b) No CORS middleware. Because the browser could still send a cross-site POST to localhost that spends money, reject any request whose `Origin` is present and not in `{http://localhost:5173, http://127.0.0.1:5173}` (env override), and any `Host` not `localhost`/`127.0.0.1` (DNS rebinding). (c) Path ids: dataset `^[a-z0-9][a-z0-9_-]{0,63}$`; `run_id` matches the server-generated pattern; `item_id` is accepted only if it is in that run's `item_ids` (B2 ids are filename-safe, `[A-Za-z0-9._-]`; C1 slugs the MeetingBank uids that contain spaces), so no extra mapping; every resolved path is checked to stay under its root. (d) Logging per `docs/implementation/logging-and-phi.md`: uvicorn access log off; own middleware logs method, route template, status, duration only (no raw paths, bodies, item ids); exceptions log class name only; request/response bodies never logged [verified: that doc's allowlist rules].

## Decisions
| # | Decision | Choice | Alternatives considered | Why |
|---|---|---|---|---|
| 1 | Framework | FastAPI + uvicorn | Starlette only; aiohttp | Matches backend; pydantic gives schema export |
| 2 | Port | 8100 | 8001; random | Next to 8000, clear of 5173; env-overridable |
| 3 | Concurrency | One run at a time | N parallel runs | Cost clarity, backend/provider rate limits (R7), one progress panel in D |
| 4 | Restart semantics | `running`→`interrupted` at startup; resume | Auto-resume | Auto-resume would spend without a click |
| 5 | Contract source | Pydantic models → exported JSON Schema, staleness test | Hand-written schema; FastAPI OpenAPI only | No drift; Ajv (already in frontend) can use JSON Schema directly |
| 6 | Schema location | `eval/api/` | `docs/contracts/` | `docs/contracts/` is the audit contract and bumps consumers together; eval API is internal to eval+UI |
| 7 | Prefix | Server at root; proxy rewrites | Server under `/eval-api` | Fewer path edits; D1 owns the one proxy line |
| 8 | Cross-site guard | Origin/Host allowlist | Token header | Single user, no secrets, zero UI work |
| 9 | Item identity | Allowlist by run `item_ids` | Regex on id only | Stricter and cheap; B2 ids are already filename-safe |
| 10 | Polling | `GET /runs/{id}` only, no push | SSE | Locked (~1 s poll) |

## Dev script (`scripts/dev.sh`)
`scripts/` does not exist yet [verified: `ls scripts`]; create it with a `scripts/README.md` index (global directory convention). Bash, `set -euo pipefail`.
- Preflight: `uv`, `node`/`npm` present; `frontend/node_modules` missing → print `npm ci` hint and exit; ports 8000/8100/5173 free (error naming the holder).
- Starts, each prefixed `[backend]`, `[eval]`, `[web]`, in own process groups:
  - `cd backend && uv run uvicorn iaudit_backend.app:app --port 8000` [verified: README]; flag `--stub` adds `IAUDIT_PIPELINE=stub` [verified: README].
  - `cd eval && uv run uvicorn iaudit_eval.server.app:app --host 127.0.0.1 --port 8100` with `IAUDIT_BACKEND_URL`.
  - `cd frontend && npm run dev` with `VITE_AUDIT_URL=http://localhost:8000/v1/audit`, `VITE_MOCK=false` (process env overrides `.env.example`'s `VITE_MOCK=true` [verified: `frontend/.env.example`, `config.ts`]) and `IAUDIT_EVAL_PORT` read by D1's Vite proxy.
- Waits for backend `/healthz` and eval `/health` (30 s), then prints the URLs.
- `trap` on INT/TERM/EXIT kills the groups (TERM, then KILL after 5 s); if any child exits, stop the rest and exit non-zero.
- Needs `ANTHROPIC_API_KEY` etc. in env for live runs; script prints a warning if none set (presence only, never values).

## Docs
| File | Content |
|---|---|
| `docs/reference/eval-api.md` (+ link in `docs/reference/README.md`) | Endpoints, states, error codes, env vars, port, schema path |
| `docs/implementation/eval-server.md` (+ `docs/implementation/README.md`) | RunManager, restart sweep, guards, schema export |
| `docs/testing/` eval note (owned by B3/D if a file exists by then) | How to run API tests |
| `scripts/README.md` | What `dev.sh` starts, flags, ports |

## Tests (`eval/tests/api/`; no network, no spend)
- Fixtures: B2's fake HTTP backend and synthetic dataset; app built via `create_app(...)` with `httpx.ASGITransport`.
- Every response of every route validated against `eval-api.schema.json`; stale-schema test.
- Flows: start→poll→finished→auto-score→metrics; abort; cap set + known costs → `aborted_cost` → resume; cap set + missing `cost_usd` → `failed`; second start→409; restart sweep (pre-seeded `running` run → `interrupted`); backend down→502; probe version mismatch→409; data missing→409; download task states.
- Guards: `../` and encoded variants in ids → 404/422; foreign Origin/Host → 403; sentinel word in a synthetic transcript never appears in captured logs (mirrors backend scenario S9).
- `bash -n` plus a `dev.sh --check` (preflight only) test stay agent-run; full script run is an owner manual check (agents do not start the real backend, eval server and frontend together).

## Manual steps
- Owner manual check: first live smoke of `scripts/dev.sh` with provider API keys in the environment (owner only). Includes AC 8 (all three up, prefixed output, Ctrl-C leaves no orphans, `--stub`). Agent-run: `bash -n`, `--check`, and the offline API tests with fakes.

## Risks / Open Questions
- [RESOLVED: B3 R8 `item_rows.json` + adapter `item_row` hook (C2)] Per-dataset `gold`/`pred`/`match` strings for the items list.
- [RESOLVED: D1 R7 adds the Vite alias + `server.fs.allow`] D reads `eval/api/eval-api.schema.json` from outside `frontend/`. B4 commits the file before D1 tests run (build order).
- [RESOLVED: B2 `probe()`, zero-spend invalid-body check plus `/healthz`; canary is the backstop (see B2 Engine)] Probe design.
- [RESOLVED: B2 `Estimate` passed through unchanged (`basis` `prior_runs`|`none`, `note`, nulls)] Estimate basis and accuracy.
- [RESOLVED: yes, 409 `run_active`] Second run while one is active.
- [RESOLVED: B2 already stores `aborted`; `interrupted` is derived by B2] State enum.
- [RESOLVED: optional run tag] `POST /runs` takes optional `tags`; default unset; no D1 UI field in v1.
- [DEFERRED] Item-list pagination UI; server supports `limit/offset`, D may load all (max 1,777 for TofuEval).
- [DEFERRED] Lockfile against two eval servers on one `eval/runs/` (port clash already prevents it).

## Acceptance Criteria
1. All routes above exist; every response validates against the committed schema; export test passes.
2. Server binds 127.0.0.1:8100 and refuses foreign Origin/Host.
3. A run survives a closed client; a simulated server restart (offline test: ASGI app + fake backend, pre-seeded `running` run) leaves it `interrupted` and resumable to completion.
4. Only one run active; second start returns 409 with the active id.
5. Backend down → 502 `backend_unreachable`; version mismatch → 409 `schema_mismatch`; no run directory is created for either.
6. Id traversal attempts never touch files outside roots.
7. No transcript text in logs; no item ids in B4's own HTTP request logs (route templates only). B2's engine logs may include filename-safe item ids per B2 R12.
8. [Owner manual check] `scripts/dev.sh` brings up all three, prefixed output, Ctrl-C leaves no orphan processes; `--stub` works.
9. Docs files listed above exist and are linked from their folder READMEs.
