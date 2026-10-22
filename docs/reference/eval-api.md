# Eval API

**Audience:** users and frontend contributors.

The local evaluation server runs at `http://127.0.0.1:8100` and calls the audit backend
at `http://127.0.0.1:8000`. Routes below are served at the root, without an `/eval-api`
prefix. A frontend proxy must strip that prefix if it uses one.

The committed contract is [eval-api.schema.json](../../eval/api/eval-api.schema.json),
a JSON Schema 2020-12 bundle. Its `$defs` contain response and request models,
`MetricsReport` and `Comparison`; `x-routes`, `x-requests` and `x-errors` map their use.
This is separate from the shared [audit contract](../contracts/README.md).

## Endpoints

Successful responses are JSON. Status is 200 unless listed otherwise. `{id}` identifies a run.

| Method and path | Input | Response definition |
|---|---|---|
| `GET /health` | None | `Health`: server status, package API version, backend URL/reachability; backend schema version is currently null |
| `GET /datasets` | None | `DatasetSummary[]`: name, title, data presence, declared splits and sizes |
| `GET /datasets/{name}` | Dataset name | `DatasetMeta`: metadata, preserving extra fields, with split sizes |
| `POST /datasets/{name}/download` | No body | 202 `DownloadStatus`; starts or reuses the dataset's background download |
| `GET /datasets/{name}/download` | Dataset name | `DownloadStatus`: status, files, error, warnings and update time |
| `POST /runs/estimate` | `EstimateRequest` | `Estimate`: rough figures from prior runs, or unknown figures and a pilot-run note |
| `POST /runs` | `RunRequest` | 202 `RunCreated`: `run_id` |
| `GET /runs` | None | `RunSummary[]`, newest first |
| `GET /runs/{id}` | Run id | `RunDetail`: summary, progress and run provenance |
| `POST /runs/{id}/abort` | No body | `RunSummary`, after the active run finishes in-flight work |
| `POST /runs/{id}/resume` | No body | `RunSummary` for the resumed run |
| `GET /runs/{id}/metrics` | Run id | `MetricsReport`; 404 until a current report is available |
| `GET /runs/{id}/items` | `filter=all\|mismatch\|failed`, optional `limit>=1`, `offset>=0` | `ItemPage`: filtered total and item rows |
| `GET /runs/{id}/items/{item_id}` | Item id from that run's selection | `ItemDetail`: stored request/response/failure, run information and current adapter gold |
| `POST /runs/{id}/rescore` | No body | 202 `RunSummary`; scoring continues in the background |
| `GET /compare` | Required `a` and `b` run ids | `Comparison`; both runs must use the same dataset |

`EstimateRequest` requires `dataset` and `split`. Optional `n` is at least 1; omitted or
null selects all items. Optional `seed` defaults to 0 during selection. `split="all"`
selects the union of declared splits. Unknown splits return 422. Extra request fields
are rejected.

`RunRequest` adds optional `max_cost_usd` (finite, nonnegative) and `tags` (a JSON object).
An omitted or null cap is unlimited. With a cap, missing reported `run_info.cost_usd`
fails the run closed; in-flight items can finish after the cap is reached and overshoot it.
Estimates do not invent missing token or cost figures.

Dataset split sizes are null when required data is absent. A data-independent adapter
needs no download. Dataset list/detail show declared splits; the implicit `all` split
is accepted when selecting items.

Item rows are sorted by item id. `total` counts the filtered rows before pagination;
omitted `limit` returns all remaining rows. `failed` selects status `failed`, while
`mismatch` selects `match=false`. Before current scoring outputs exist, rows come from
stored item files with null gold, prediction and match; items without a stored result
are absent. Item detail computes gold on demand, without persisting it. The report's
row gold/prediction fields are labels; item-detail gold is arbitrary JSON described by
`gold_kind`. Both requests and responses can contain sensitive source text.

## States and progress

Run state is one of `running`, `finished`, `aborted`, `aborted_cost`, `interrupted`, or
`failed`. `finished` can include failed items. `interrupted` is derived when a stored
running run has no held writer lock; restarting the server does not automatically
resume it or spend money. Resume retries failed or missing results and preserves
successful results. Allowed states are aborted, aborted_cost, interrupted, failed, and
finished with failures. Resume has no mixed-fingerprint override. Its optional JSON body
`ResumeRequest` is `{"max_cost_usd": number > 0 | null}`: no body or an absent key keeps
the stored cost cap, `null` clears it, a number replaces it. A resume refused because the
backend's models/prompts or schema version changed ends in the run's prior state; detail
`resume_refusal` (`kind` `fingerprint_changed` or `schema_version_changed`, `changes` of
`{field, was, now}`) reports the last refusal, kept in memory only and cleared by the next
resume. Server shutdown stops dispatching and gives in-flight items a grace period to be
saved before cancelling; the run stays `interrupted` and resumable.

Only one audit run is active per server. Abort requires that run to be active and lets
in-flight requests finish. Rescore is refused for a running run or a run already being
scored. A run and its scoring work outlive the requesting browser connection.

`score_state` is `pending`, `running`, `done`, or `failed`. `pending` means scoring is
queued or about to start: reading a terminal (including interrupted) run whose metrics are
missing or older than its run/item files schedules scoring once per run revision per
process, so it resolves to done or failed (a failed score is not retried until the run
changes or Rescore). A current metrics file makes it done. Failed scoring
can be retried explicitly. Download state is `not_downloaded`, `downloading`, `ready`,
or `failed`; there is at most one download task per dataset. Failed download responses
use the fixed error message `Download failed.`; private persisted diagnostics are not
returned by the API.

Run summaries expose selection, timestamps, schema version, states, git dirty flag,
and totals (`cost_usd`, `failures`). Run detail adds progress (`done`, `total`,
`failures`, `cost_usd`) and provenance: git commit/dirty flag, model/prompt fingerprint,
mapping version, seed, concurrency, cap, tags, mixed flag and warnings. Unknown costs
remain null. Poll run detail for progress; no event stream is provided.

## Errors

Errors use `{"error":{"code":"...","message":"...","detail":...}}`; detail is optional.
Validation detail contains locations and error types, without rejected input values.

| Code | HTTP status | Meaning |
|---|---|---|
| `invalid_request` | 422 | Invalid body/query, selection, split or comparison; different datasets cannot be compared |
| `not_found` | 404 | Unknown or unsafe dataset/run/item, missing result, or unavailable current metrics |
| `run_active` | 409 | Another run is active; detail includes its run id |
| `bad_state` | 409 | Invalid abort/resume/rescore state, conflicting scoring, resume refusal, or shutdown |
| `data_missing` | 409 | Required dataset data is absent |
| `backend_unreachable` | 502 | Backend/probe unavailable or unable to accept the requested version without a reported mismatch |
| `schema_mismatch` | 409 | Probe reports a different contract version; detail contains expected/received versions |
| `forbidden` | 403 | Host or Origin rejected |
| `internal_error` | 500 | Unexpected failure; fixed message, without exception text |

Unsupported HTTP methods also use `invalid_request` with HTTP 405. Start/resume probes
happen before creating a new run; a failed start probe creates no run directory.
`GET /health` only checks backend health and never starts an audit or version probe.

## Configuration and local safety

| Variable | Default | Effect |
|---|---|---|
| `IAUDIT_EVAL_PORT` | `8100` | Port used by the Python server entrypoint |
| `IAUDIT_BACKEND_URL` | `http://127.0.0.1:8000` | Audit backend URL |
| `IAUDIT_EVAL_ALLOWED_ORIGINS` | `http://localhost:5173,http://127.0.0.1:5173` | Comma-separated exact Origin allowlist |
| `IAUDIT_EVAL_ALLOW_REMOTE` | unset | `1` allows a non-default `--host` through the Python entrypoint's bind check and non-loopback peers |
| `IAUDIT_EVAL_HOME` | Repository `eval/` | Root for datasets, downloaded data and run outputs |
| `IAUDIT_CONTRACTS_DIR` | Repository `docs/contracts/` | Shared audit schemas; eval report/API schemas stay with the code |

For a manual launch, use `cd eval && uv run python -m iaudit_eval.server.app`. It accepts
`--host` and `--port`. It defaults to `127.0.0.1` and disables uvicorn access logs.
Direct uvicorn invocation bypasses that entrypoint's bind validation, but the app still
rejects (403 `forbidden`) any request whose socket peer address is not loopback
(127.0.0.0/8, `::1`) unless `IAUDIT_EVAL_ALLOW_REMOTE=1`. Explicitly bind
`127.0.0.1` and pass `--no-access-log`, as the [development script](../../scripts/README.md)
does. That script fixes ports at 8000/8100/5173 and supplies its own matching environment.

Host must be `localhost` or `127.0.0.1`, optionally with a port. Requests without Origin
are accepted; a supplied Origin must match the configured allowlist. There is no CORS
middleware or authentication. Remote bind permission relaxes only the peer-address check,
not the Host/Origin guards.
The server is intended for local use, without public hosting. Logs omit raw paths,
queries, bodies and item ids; HTTP logging uses route templates.

See [server internals](../implementation/eval-server.md) for lifecycle and schema export.
Full-stack launches (including `--stub`), live backend runs and real dataset downloads
are owner-only checks. Offline tests and `scripts/dev.sh --check` do not perform a live smoke.
