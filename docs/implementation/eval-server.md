# Eval server internals

**Audience:** maintainers and coding agents.

The [eval API reference](../reference/eval-api.md) describes public routes and configuration.
The implementation lives in [iaudit_eval/server](../../eval/src/iaudit_eval/server/).
It calls the backend over HTTP; it never imports backend code or duplicates audit schemas.

## Application and ownership

`app.create_app(settings, backend_client, runs_root, datasets_root, data_root)` supports
injected clients and roots for offline tests. Settings live in `guards.py`. Lifespan
creates an `AuditClient` when none was injected, starts the `RunManager`, then shuts the
manager down before closing the owned client. Injected clients retain caller ownership.
The app stores both `RunManager` and `RunReader` on application state.

Thin health, dataset, control and read routers delegate work. Blocking adapter reads,
filesystem operations, preparation, downloads, scoring and comparisons run through
`asyncio.to_thread`. Engine tasks and HTTP clients remain on the application's event loop.
The health route calls only backend `/healthz`; schema version is null because that
endpoint does not supply one. Version probes occur on explicit start/resume.

## Run lifecycle

`RunManager` serializes control changes with a lock and owns one active engine handle
and its observer. Start validates the dataset/split and required data, probes backend
reachability/version, then calls `engine.start_run_async`. That engine entrypoint moves
synchronous preflight and persistence preparation to a worker thread before creating
the engine task on the event loop. Failed reachability/version checks create no run.
Engine preflight validates every adapter request before audit POSTs; its first selected
item is the canary before parallel dispatch.

The observer waits for the engine, clears the active handle, and schedules B3 scoring
unless shutdown is underway. Scoring runs in a worker thread, with in-memory
`score_states` and tasks keyed by run id. A scoring exception records `failed` and
logs only the exception class. Rescore is explicit and blocked while that run is
active or already scoring. Resume also refuses concurrent scoring for the same run.
Other runs may be scored while the single active audit run proceeds.

Abort requests the engine's cooperative stop and waits for the observer; in-flight
requests finish. Resume validates stored state and current data, probes the backend,
and invokes `engine.resume_async` to retry only failed/missing items. This HTTP route
exposes no `allow_mixed` override: changed model/prompt fingerprints remain refused.
Budget handling belongs to B2: unset means unlimited; a set cap fails closed if cost
is missing and permits already-dispatched requests to finish.

Download tasks are independent of audit runs and deduplicated per dataset. Ordinary
status and hashes are persisted by B2's download framework. Failed download status
is sanitized to `Download failed.` at the API boundary; B2's private persisted
diagnostic remains on disk. An infrastructure failure outside the framework's normal
boundary also produces that fixed in-memory failure message.

## Restart and shutdown

Startup resets any retained in-memory running scoring state to pending. It does not
rewrite run states or automatically resume them. B2 derives `interrupted` from stored
`running` state with no held `run.lock`, so a crashed run becomes resumable without
startup spending. On a fresh server, score state is reconstructed from current files:
metrics must be at least as new as the run and item files. Changed/resumed runs cannot
serve an old report as current merely because `metrics.json` exists.

Shutdown first refuses new run controls, cancels the actual engine task, and waits
for it to clean up. The initial grace is two seconds; exceeding it does **not** detach
the engine or close its transport early. Shutdown continues awaiting actual cleanup,
then reaps the observer and releases the writer lock idempotently, including when a
task was cancelled before its first step. Stored running state then reads interrupted.
Scoring/download tasks are awaited; an owned backend client closes afterward. Slow
cleanup can therefore extend shutdown beyond the initial grace period.

## Read projections

`RunReader` runs in worker threads. Summaries recompute totals from item files and use
B2's effective state. Run listing ignores incomplete/foreign directories and sorts by
creation time and id, descending. Metrics are schema-validated before return and only
served when current. Item rows use validated `item_rows.json` when it is current with
metrics, otherwise they come from stored item files with null gold/prediction/match.
Filtering precedes pagination, and row ids must belong to the run's selected item ids.
Item detail loads the adapter and computes current gold on demand; gold is not added
to the persisted audit result. Comparisons validate both runs, reject cross-dataset
pairs, delegate to B3, and validate the resulting report.

## Guards, errors and logging

The Python entrypoint validates bind host before starting uvicorn. Calling uvicorn
directly bypasses that check, so the supported dev script explicitly binds loopback
and disables access logs. `IAUDIT_EVAL_ALLOW_REMOTE=1` affects only entrypoint bind
validation; Host and Origin guards remain active. There is no CORS middleware.

Host is limited to localhost/127.0.0.1 with an optional port; an Origin, when supplied,
must exactly match the configured allowlist. Dataset names and generated run ids have
separate validators. Item ids must satisfy B2's filename-safe contract and belong to
the selected run. `resolve_under` rejects traversal and paths/symlinks resolving
outside the configured root before storage/adapter reads.

Error handlers produce the uniform API envelope. Validation errors expose locations
and types rather than rejected values; unexpected failures use a fixed message.
Outer HTTP middleware logs method, route template, status and duration, plus exception
class when needed. Unmatched/guard-rejected routes use `-`; raw URLs, item ids, query
strings and bodies are not logged. Uvicorn access logging is disabled in both the
Python entrypoint and eval's dev-script invocation. See [logging and PHI](logging-and-phi.md).

## Contract export and offline verification

Pydantic models in `models.py` define request/response fields and enums. B3's metrics
and comparison JSON schemas remain their own sources. `export_schema.build_schema`
bundles those resources intact under `MetricsReport` and `Comparison`, retaining their
local `$id`/`$defs` for reference resolution. The bundle also includes route, request
and error maps; it is not FastAPI's generated OpenAPI document.

After an intentional model/report change, export from `eval/`:

```bash
uv run python -m iaudit_eval.server.export_schema
uv run pytest tests/api
uv run ruff check src tests
```

The exporter writes [eval/api/eval-api.schema.json](../../eval/api/eval-api.schema.json)
and accepts `--output` for another destination. Tests compare generated/committed
content and bundled B3 resources, validate route responses, and exercise guards,
background controls, restart, shutdown and sensitive-data logging with fake clients
and fictional fixtures. They require no listening backend, provider keys or real data.
See [evaluation testing](../testing/evaluation.md).

Full-stack launches, including the script's `--stub` mode, real dataset downloads and
live audits remain owner-only manual checks. `bash -n scripts/dev.sh` and
`bash scripts/dev.sh --check` are offline syntax/preflight checks, not live smoke tests.
