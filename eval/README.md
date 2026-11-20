# iaudit-eval

Evaluation engine for the Interview Evidence Auditor, with an offline test suite. It sends dataset
items to a running backend's `POST /v1/audit`, stores results under `runs/`, and scores them. Scope: see
[the mission](../docs/mission.md). Audit contracts are read from the
[shared audit contracts](../docs/contracts/) (never copied here); the backend is only reached
over HTTP, never imported.

## Layout

- `src/iaudit_eval/` - engine package: `paths`, `log`, `contracts`, `datasets/` (plug-in API),
  `selection`, `store`, `client`, `engine` (start/resume/probe, cost cap), `estimate`,
  `download`, `metrics/`, `scoring`, `compare`, `server/` (HTTP API).
- `datasets/<product>/<name>/` - one folder per dataset: `metadata.json` and `adapter.py`.
  `datasets/eaudit/synthetic/` is a small fictional set for zero-spend tests.
- `schemas/` - eval's own report schemas (`metrics`, `item_rows`, `compare`). No audit-contract copies.
- `tests/` - offline tests; no API key or network needed.
- `runs/`, `data/` - run output and downloaded data (under `IAUDIT_EVAL_HOME`, default `eval/`).

Scoring (metrics, `scoring`, `compare`) and the HTTP server (`server/`) are documented in the
[eval API reference](../docs/reference/eval-api.md) and
[server internals](../docs/implementation/eval-server.md); see also the module docstrings. The
engine is a library with no CLI; `server/` is its local HTTP API.

Paths are resolved from the installed module's repository location, independent of the working
directory. `IAUDIT_EVAL_HOME` overrides the root for **datasets, data and runs**; populate its
`datasets/` directory when using this override. `IAUDIT_CONTRACTS_DIR` overrides the shared audit
contract directory. Eval report schemas remain in `eval/schemas/`. Runs and downloaded data are
gitignored; created directories are private (0700), and stored files are private (0600).

## Tests

```
cd eval
uv run pytest
uv run ruff check src tests
```

Tests use fictional items and `httpx.MockTransport`; provider keys and a running backend are
unnecessary. Contract boundary tests check for backend imports and copied audit schemas.

## Writing a dataset adapter

Create `eval/datasets/<product>/<name>/metadata.json` and `adapter.py` (or use the configured eval home).
Use a folder name matching `[A-Za-z0-9_-]+`; the metadata `name` must match it. Dataset names
must be unique across products. Import `Item` and `Unmapped` from `iaudit_eval.datasets.base`, and use `iaudit_eval.datasets.registry.load(name)`
to load and exercise the adapter. Do not import backend modules.

`metadata.json` keys: `name` (required, string), `title`, `description`, `dataset_version`,
`kind` (default `adapter`), `splits` (list of `{name, description}`), `default_split`,
`cluster_key`, `license` (`name`, `redistributable`, `contains_licensed_text`), `data_required`,
`sources`, `test_split_note`, `slices` (item `meta` keys to slice by), `mapping`, `references`,
`levels` (per level: `labels`, `positive`), `metrics`, `pool_all`, `gold_kind`. Unknown keys are
preserved. The split name `all` is reserved: the union of declared splits.

`adapter.py` exposes `create(data_dir)` returning an adapter. `data_dir` is where downloaded data
lives (unused when `data_required` is false).

`Item(id, doc_id, split, payload, meta)`:

- `id`: unique in the dataset, matches `[A-Za-z0-9._-]{1,128}` (used as a filename).
- `doc_id`: cluster key (source document), used for clustered resampling.
- `payload`, `meta`: JSON-serialisable; `meta` holds slice attributes.

Required methods:

- `items(split) -> Iterable[Item]`
- `to_request(item) -> dict` - an audit request (validated against the request contract)
- `gold(item)` - gold label
- `project(response, item)` - map an audit response to the gold label space; raise `Unmapped`
  when it cannot be mapped (counted as a failure, not guessed)

Check each declared split and the `all` union, deterministic selection, schema-valid requests,
and gold/projection behavior with fictional or appropriately licensed fixtures. Preserve the
interview's actual source locations and uncertainty when constructing requests; do not invent
quotations, speaker identities, or timestamps. Bump `dataset_version` when items or gold change.

Optional hooks, found with `getattr`: `post_download`, `download`, `pairs`, `item_row`,
`mapping_version`, `report_extra`. See `datasets/eaudit/synthetic/adapter.py` for a worked example.

## Manual (owner) steps

These need credentials, network or spend and are not run by the test suite:

1. For a real adapter, review its license and sources, then call
   `iaudit_eval.download.download(dataset)`. Confirm `status` is `ready` and inspect the recorded
   hashes in `data/<name>/download.json`; pinned hashes must match before running.
2. Start the real backend with provider keys and use `iaudit_eval.engine.probe(base_url)` to check
   reachability and contract compatibility. The probe uses an invalid body to avoid an audit call.
3. Select a small pilot with `iaudit_eval.selection.select(dataset.items(split), n=5, seed=0)`,
   call `iaudit_eval.engine.start_run(dataset, selection, base_url=..., max_cost_usd=...)` from an
   async application, and await the returned handle's `wait()`. Check the first-item canary,
   validated per-item results and stored run totals. The cap requires reported `run_info.cost_usd`;
   missing cost fails closed, and in-flight items can overshoot a cap. An unset cap is unlimited.
4. Check reported cost, abort/resume behavior and latency at concurrency 4 before a larger run.
   The backend's default deadline is 100 s; the eval client waits up to 120 s. Estimates are rough
   ratios from prior runs; a cold start reports unknown cost and latency.
5. MeetingBank equality check: deferred to sub-project C.
