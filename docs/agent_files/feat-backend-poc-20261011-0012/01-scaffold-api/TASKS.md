---
status: approved
summary: Ten core tasks for the FastAPI scaffold, contract loader, errors, config, LLM client, pipeline seam, endpoint, logging and a live model check; one gated optional row.
date: 2026-10-11
---
# Tasks: 01 Scaffold + API

Source of truth: [PRD.md](PRD.md). A runnable `backend/` service serving `POST /v1/audit` and `GET /healthz` against contract 1.0.0, with a stub pipeline. Tests run offline (`LLM_MODE=stub`, `IAUDIT_PIPELINE=stub`).

| # | Task | Depends on | Status |
|---|---|---|---|
| 1 | Project skeleton: uv, ruff, pytest, src layout | none | todo |
| 2 | Contract loader: schemas read in place, fail at startup | 1 | todo |
| 3 | `IAUDIT_*` settings | 1 | todo |
| 4 | Internal models and enum-drift test | 2 | todo |
| 5 | Error mapping to contract error bodies | 2 | todo |
| 6 | LLM client: LiteLLM, fixture, stub and failing clients | 3 | todo |
| 7 | Pipeline seam, `StubPipeline`, factory, 504 backstop | 4, 6 | todo |
| 8 | `POST /v1/audit` checks in order, `/healthz`, CORS | 5, 7 | todo |
| 9 | Logging allowlist and sentinel test | 8 | todo |
| 10 | One live call to confirm model ids and JSON-schema output | 6 | todo |
| 11 | [OPTIONAL, gated] Optional items | all core in every SP | todo |

## Task 1 — Project skeleton
What it is / what it means: The shared home every later sub-project builds in (R1, D5).
What changes at a high level: Create `backend/` with `pyproject.toml` (Python 3.12, uv, package `iaudit_backend` in src layout), committed `uv.lock`, ruff and pytest config, and the declared dependencies (fastapi, uvicorn, pydantic v2, pydantic-settings, jsonschema + referencing, litellm, httpx). No spaCy, torch or embedding deps.
Done when: `uv run pytest` and `uv run ruff check` pass on an empty test suite.

## Task 2 — Contract loader
What it is / what it means: The schemas in `docs/contracts/` are the single validator (R2, D1).
What changes at a high level: Load the three schemas in place (override `IAUDIT_CONTRACTS_DIR`), build a `referencing.Registry` by `$id`, cache compiled Draft 2020-12 validators, and expose `validate_request`, `validate_response`, `validate_error`. A missing or invalid schema fails startup.
Done when: the example request and response validate; removing the contracts dir makes startup fail with a clear message (acceptance 7).

## Task 3 — Settings
What it is / what it means: One frozen, env-driven config object (R5).
What changes at a high level: pydantic-settings with prefix `IAUDIT_` for limits (2 MB / 2,000 turns / 50 sections), CORS origins, model tiers (`anthropic/claude-haiku-4-5-20251001`, `anthropic/claude-sonnet-5-5`, `anthropic/claude-opus-5-5`), timeouts, retries, concurrency, `LLM_MODE`, `FIXTURE_DIR`, `LOG_LEVEL`, `PIPELINE` (default `stub` in this SP). Startup logs the non-secret effective config. API keys stay in provider env vars.
Done when: tests show defaults and env overrides; no key is ever stored in `Settings`.

## Task 4 — Internal models and enum-drift test
What it is / what it means: Convenience Pydantic models that mirror the contract, with the schema as authority (R7, D6).
What changes at a high level: Request and response models (`Turn.role` optional), enums for verdicts, concerns (check order 1-12), roles, warnings and evidence roles, serialized with `exclude_none` and contract field names.
Done when: a test asserts every model enum equals the schema enum (acceptance 11).

## Task 5 — Error mapping
What it is / what it means: Every non-2xx body validates against the error schema (R4, D3, D12).
What changes at a high level: One `ApiError(code, message, status)` and handlers for the R4 table, including Starlette 404/405, `RequestValidationError` (422) and bare `Exception` (500, fixed generic message). Messages carry schema paths and schema messages only, never instance values.
Done when: table-driven tests hit every R4 row and every body validates against `error-response.schema.json`.

## Task 6 — LLM client
What it is / what it means: The single async interface stages 03-06 call (R6, D7-D10).
What changes at a high level: `LLMClient` protocol with `LiteLLMClient` (JSON-schema output, `num_retries=0`, one deadline-gated transport retry, per-call `asyncio.timeout`, global semaphore, single `cache_prefix` as a `cache_control` block), typed errors (`LLMTimeout`, `LLMUnavailable`, `LLMBadOutput`), `FixtureClient` with `FixtureMiss`, `StubClient`, `FailingClient`, and a basic append-only `MetricsCollector` with `snapshot()`. `CancelledError` is never caught.
Done when: acceptance 9 core passes against a faked `acompletion` (timeout, one retry, bad JSON, usage and latency captured, `cache_control` present when `cache_prefix` is set).

## Task 7 — Pipeline seam
What it is / what it means: The slot 06 later fills (R8, D11).
What changes at a high level: `Pipeline` protocol, `RequestContext` (settings, llm, metrics, request_id, deadline, `remaining()`, `call_timeout()`, `fixture_scope`), `StubPipeline` returning a valid empty audit, a factory reading `IAUDIT_PIPELINE`, and the `asyncio.timeout` 504 backstop.
Done when: the stub response validates and a forced timeout maps to 504.

## Task 8 — Endpoint
What it is / what it means: The request path in the order R3 requires (R3, D2, D4).
What changes at a high level: Raw-`Request` route: size check (Content-Length, else read then check), own JSON parse, version check before schema, turn and section limits, schema validation in a worker thread, duplicate turn and section ids (count-only message), parse, run pipeline, validate response. `request_id` echoed on errors when readable. Add `/healthz` and the CORS allowlist.
Done when: acceptance 2-6 and 8 pass, including boundary limits and a turn without `role`.

## Task 9 — Logging allowlist
What it is / what it means: No transcript or assessment text ever reaches logs (R9, D12).
What changes at a high level: `log_event(**fields)` allowlist helper that drops text-like field names; one INFO line per request with counts, status and token sums; exceptions logged as class and frames only.
Done when: a sentinel string in the transcript is absent from logs and error messages on every path (acceptance 10).

## Task 10 — Live model check
What it is / what it means: Confirms the resolved model ids (O-1).
What changes at a high level: One opt-in live call per tier through `LiteLLMClient` with `ANTHROPIC_API_KEY`, confirming the `anthropic/...` id form and that JSON-schema output is honored. Not part of the offline suite.
Done when: both tiers return schema-valid JSON once; result noted on the PR. Blocks nothing else; needs the key.

## Task 11 — [OPTIONAL, gated] Optional items
What it is / what it means: The PRD's Optional tier, started only after all core work in every sub-project is done.
What changes at a high level: Streaming body-size cap, richer metrics (`unit`, stage spans), `Server-Timing`, multiple cache breakpoints.
Done when: each optional acceptance part passes.
