---
status: draft
summary: Eight tasks for the local eval FastAPI server (guards, schema export, dataset and run routes, RunManager), offline API tests, scripts/dev.sh and docs.
date: 2026-10-20
---
# Tasks: 04 Eval API server + dev script

Source of truth: [PRD.md](PRD.md). A localhost FastAPI server over B2/B3 with a committed JSON Schema for every response, plus `scripts/dev.sh` to start backend, eval server and frontend. Implementing agents make no live LLM calls, real downloads or live smoke runs; tests use the fake backend and synthetic dataset from B2.

| # | Task | Depends on | Status |
|---|---|---|---|
| 1 | Server skeleton: app factory, error body, guards, safe logging | none | todo |
| 2 | Response models and schema export with staleness test | 1 | done |
| 3 | Health, datasets and download routes | 1, 2 | done |
| 4 | RunManager and run control routes | 2, 3 | done |
| 5 | Run read routes: list, detail, metrics, items, compare | 4 | done |
| 6 | Cross-cutting offline API tests | 3, 4, 5 | done |
| 7 | `scripts/dev.sh` with `--check` and scripts README | 1 | todo |
| 8 | Docs: reference, implementation, indexes | 5, 7 | done |

## Task 1 — Server skeleton
What it is / what it means: The shell every route sits in (R1, R2, R5, R6, D1, D2, D7, D8).
What changes at a high level: Add `fastapi` and `uvicorn` to the eval project. Create the server package with a `create_app` factory taking injected settings, backend client and roots, bound to 127.0.0.1:8100 (`IAUDIT_EVAL_PORT`, `IAUDIT_BACKEND_URL`), refusing other hosts unless `IAUDIT_EVAL_ALLOW_REMOTE=1`. Add the uniform error body and handlers for the PRD code table (500 fixed message only), no CORS middleware, Origin and Host allowlist (403, env override), dataset, run and item id validators with path-under-root checks, and a logging middleware (access log off; method, route template, status, duration only).
Done when: unit tests show foreign Origin/Host give 403, malformed or traversal ids are rejected, and every error body matches the shape.

## Task 2 — Models and schema export
What it is / what it means: The pydantic models are the API contract D codes against (R7, D5, D6).
What changes at a high level: Define request and response models for the endpoint table (Health, DatasetSummary, DatasetMeta, DownloadStatus, Estimate, RunSummary, RunDetail, ItemPage, ItemRow, ItemDetail, errors) with the state and score_state enums. Add `export_schema` writing `eval/api/eval-api.schema.json` with `$defs`, an `x-routes` map, and B3's metrics and compare schemas bundled as `MetricsReport` and `Comparison`. Commit the generated file.
Done when: a test fails when the committed file is stale, and a test asserts the bundled copies equal `eval/schemas/*`.

## Task 3 — Health, datasets, downloads
What it is / what it means: The read-mostly half of the API (R3, R4; AC 1, 5).
What changes at a high level: Thin routes for `GET /health` (probes backend `/healthz`, reports reachability and schema version), dataset list and meta (sizes null when data absent), and download start and status. Downloads run as one asyncio task per dataset via the manager, with blocking work in `asyncio.to_thread`, reporting the B2 status enum. Unknown dataset gives 404.
Done when: tests with the fake backend and synthetic dataset cover all states, backend-down health, and download states; all responses validate against the schema.

## Task 4 — RunManager and run control
What it is / what it means: Runs outlive the client and spend only on an explicit click (R4, D3, D4, D10; AC 3, 4, 5).
What changes at a high level: `RunManager` owns at most one engine task. Implement estimate (B2 `Estimate` unchanged), start (validate, data present, B2 `probe()`, write `run.json`, spawn task, 202), abort, resume (allowed states per PRD), rescore (refused while running) and the chained B3 `score()` with in-memory `score_state`. Add 409 `run_active` carrying the active id, `schema_mismatch` and `backend_unreachable` creating no run directory, cost cap fail-closed, lifespan startup reset of `score_state` and shutdown that cancels the task with a short grace period and releases the lock.
Done when: flow tests pass for start to finished to scored, abort, cap and `aborted_cost` then resume, missing cost failing closed, second start 409, and a pre-seeded `running` run reading `interrupted` and resuming.

## Task 5 — Run read routes
What it is / what it means: Everything the UI reads while and after a run (R3; AC 1, 6).
What changes at a high level: `GET /runs`, run detail (summary, progress, `run_info`), metrics (404 until written), items page with `filter` and `limit`/`offset` reading `item_rows.json` or building generic rows from item files before scoring, item detail (id allowlist from the run's `item_ids`, gold computed on demand via the adapter, never persisted), and `GET /compare` (refused across datasets).
Done when: tests cover filters, pagination, unscored runs, item allowlist, cross-dataset compare refusal, and schema validity of each response.

## Task 6 — Cross-cutting offline API tests
What it is / what it means: Safety and contract checks spanning all routes (R6, R7; AC 1, 2, 6, 7).
What changes at a high level: A parametrized test that every route's responses validate against the committed schema; encoded and `../` id variants returning 404/422 and touching nothing outside roots; foreign Origin/Host across routes; a sentinel word in a synthetic transcript absent from captured logs and error messages on every path. Built on `create_app` with `httpx.ASGITransport`; no network or spend.
Done when: the full `eval/tests/api/` suite passes offline.

## Task 7 — `scripts/dev.sh`
What it is / what it means: One command to start all three processes with matching ports and env (Dev script section, D2; AC 8).
What changes at a high level: Create `scripts/` with `dev.sh` (`set -euo pipefail`) and `scripts/README.md`. Preflight for `uv`, `node`/`npm`, `frontend/node_modules` (print `npm ci` hint) and free ports 8000/8100/5173 naming the holder; a `--check` flag that runs preflight only; a `--stub` flag setting `IAUDIT_PIPELINE=stub`. Start backend, eval server and Vite in own process groups with `[backend]`/`[eval]`/`[web]` prefixes and the specified env, wait up to 30 s on both health endpoints, then print URLs. Trap INT/TERM/EXIT: TERM then KILL after 5 s; if any child exits, stop the rest and exit non-zero. Warn on absent provider keys (presence only).
Done when: `bash -n` and `--check` pass offline. No live run by the agent.

## Task 8 — Docs
What it is / what it means: Reference and maintainer docs (Docs section; AC 9).
What changes at a high level: Write `docs/reference/eval-api.md` (endpoints, states, error codes, env vars, port, schema path) and `docs/implementation/eval-server.md` (RunManager, restart behavior, guards, schema export), link both from their folder READMEs, add a short API-test note in `docs/testing/` only if an eval file already exists there, and confirm `scripts/README.md` is complete.
Done when: all listed files exist, are linked from their READMEs, and match the implemented behavior.

## Owner manual checks
- First live smoke of `scripts/dev.sh` with provider API keys in the environment (AC 8): all three processes up, prefixed output, Ctrl-C leaves no orphans, `--stub` works.
- Any real dataset download or live run through the server is owner-run.
