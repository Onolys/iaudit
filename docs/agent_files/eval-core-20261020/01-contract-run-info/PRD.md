---
status: draft
summary: Add optional run_info (models, prompt hashes, tokens, optional cost_usd) to AuditResponse and move the whole contract, backend, frontend, examples and tests to 1.1.0 in one change.
date: 2026-10-20
---
# PRD: B1 Contract run_info (1.1.0)

Repo/branch: iaudit / `users/codex/eval-investigation` · Depends on: none (first of B1 → B2 → B3 → B4 → C1 → C2 → D1 → D2 → A1) · Owns: `docs/contracts/` (3 schemas, README, examples), `docs/examples/{mock,real,README.md,curl.md}`, `docs/reference/{backend-api,review-ui}.md`, `docs/testing/pre-release-checklist.md`, new ADR 0014, `backend/src/iaudit_backend/{app.py,run_info.py,pricing.py,models/audit.py,api/errors.py,assembler/__init__.py}`, backend tests, `backend/eval/adhd.py` + `backend/eval/data/adhd/requests/*.json` (version string only), `frontend/src/contract/{types.ts,validate.ts}` + frontend tests

## TL;DR
Every successful audit response may carry `run_info`: model id per tier, prompt hashes, summed tokens, and `cost_usd` when the backend has a price. This is what lets the eval (B2+) record provenance and cost over plain HTTP. The schema is one shared version, so the bump to **1.1.0** touches request, response and error schemas and every consumer at once. The Audit UI ignores `run_info`.

## Problem
- Token usage and models exist only inside the backend (`MetricsCollector` in `llm/types.py`, `Settings.model_*`), logged as counts but not returned. The eval cannot sum cost or prove which prompts/models produced a run without importing backend code (forbidden by brief decision 2).
- Prices live only in `backend/eval/prices.json` (eval-side estimates), so the backend cannot compute `cost_usd`.
- All three schemas hard-code `const "1.0.0"` and consumers must reject anything else, so adding a field forces a coordinated bump.

## Goals / Non-Goals
**Goals**
- Optional `run_info` in AuditResponse; old 1.0.0-shaped bodies minus the version still validate structurally.
- Backend populates it from live data; contains no transcript/assessment text.
- 1.1.0 everywhere in one change; CI (`ci.yml`) and nightly (`nightly.yml`) stay green.
- Backend-owned price table; `backend/eval` unbroken.

**Non-Goals**
- Displaying `run_info` in the Audit view.
- Per-stage or per-call breakdowns, latency fields (Server-Timing already covers latency).
- Changing `backend/eval` price logic or `eval/run.py` hashing (consolidation is [DEFERRED]).
- Accepting both 1.0.0 and 1.1.0 (contract rule: reject any other value).
- Any pipeline/prompt change; `run_info` on error bodies.

## Requirements
1. A successful `POST /v1/audit` (pipeline `full`, at least one LLM call made) returns `run_info`; omitted for the `stub` pipeline or zero calls.
2. `run_info.models`: ids actually configured for `cheap`, `mid`, `strong`.
3. `run_info.prompt_hashes`: one hash per prompt group, stable across restarts and machines for identical files.
4. `run_info.input_tokens` / `output_tokens` / `cache_read_tokens` / `cache_write_tokens`: totals over all recorded calls.
5. `run_info.cost_usd`: present only when every model that made a call has a price; otherwise omitted (tokens still present).
6. Request, response, error schemas and every producer/consumer say `1.1.0`; anything else is rejected as before (`unsupported_version` on the backend, `wrong_version` in the frontend).
7. Audit view renders identically with and without `run_info`.

## Architecture
**Schema** (`audit-response.schema.json`, new optional top-level property; `additionalProperties:false` stays, so the property must be declared):
```json
"run_info": {
  "models": {"cheap": "str", "mid": "str", "strong": "str"},
  "prompt_hashes": {"atomize": "16hex", "link": "16hex", "check": "16hex", "prep": "16hex"},
  "input_tokens": 0, "output_tokens": 0, "cache_read_tokens": 0, "cache_write_tokens": 0,
  "cost_usd": 0.0
}
```
Required inside `run_info`: `models`, `prompt_hashes`, the four token fields. Optional: `cost_usd` (number, `minimum: 0`). All inner objects `additionalProperties:false`.

**Backend data flow**
```
app._audit -> pipeline -> result.to_json() -> out
  + run_info.build(settings, ctx.metrics.snapshot())   # new, after pipeline, before validate_response
  -> contract.validate_response(out) -> JSONResponse
```
- New `run_info.py`: `build(settings, snapshot) -> dict | None`; `prompt_hashes()` computed once at import/startup and cached. Same algorithm as `backend/eval/run.py::prompt_hashes` (sha256 over file bytes of `*_system.md` + `*_fewshot.json`, first 16 hex; prep = hash of `prep.prompt.SYSTEM`) so values equal the recording manifest's.
- New `pricing.py`: `PRICES` ($/Mtok input, output; cache read/write multipliers) matched on a model-id fragment, same convention as `eval/prices.json`; `cost(model, usage) -> float | None`. Cost computed per tier from `snapshot["by_tier"]` and the model configured for that tier.
- Assembler stays pure (does not know run_info). Attach in `app.py` so stub/fixture paths are handled in one place.
- `AuditResponse` pydantic model gets an optional `run_info`; `to_json` already drops `None`.
- PHI: `run_info` holds ids, hashes and counts only. No new log fields needed; existing `audit_request` log already carries token counts. Sentinel test S9 (`tests/latency/test_latency.py`) extended to assert the sentinel never appears in `run_info`.

**Frontend**: `types.ts` gets `run_info?: RunInfo`, both literals become `"1.1.0"`; `validate.ts` compares to `"1.1.0"`. The JSON Schema (via `@contracts`) does the structural check. No component reads `run_info`.

**Change surface** [verified: `grep -rl '1\.0\.0'`, excluding node_modules/agent_files]

| Area | Files | Notes |
|---|---|---|
| `docs/contracts/` | 11 | 3 schemas (const + description), README (7 hits), 7 examples (error, 2 request/response pairs, default pair) |
| `docs/examples/mock/` | 22 | 10 requests, 10 responses, `validate.py` (`VERSION`), README |
| `docs/examples/real/` | 10 | requests only (13 dirs; 10 carry the string) |
| other docs | ~9 | `reference/{backend-api,review-ui}`, `testing/pre-release-checklist`, `examples/{README,curl}`, `backend/README`, ADR 0010 and `concepts/limits-of-an-audit` (historical mentions, leave) |
| `backend/src` | 4 files, 5 sites | `app.py:36` SUPPORTED_VERSION, `models/audit.py:78,126`, `api/errors.py:14`, `assembler/__init__.py:92` |
| `backend/pyproject.toml` | 1 | description string |
| `backend/tests` | 4 | test_contract, test_claims, test_repair, test_prep_optional |
| `backend/eval` | 1 + 10 | `adhd.py:21`; pinned `data/adhd/requests/*.json` (version string only; transcript sha pin unaffected) |
| `frontend/src` | 11 | `types.ts` (2), `validate.ts`, 9 test/fixture files |

Not touched: `.github/workflows/*` (both only run pytest/vitest/`eval.run --mode oracle`).

## Decisions
| # | Decision | Choice | Alternatives considered | Why |
|---|---|---|---|---|
| 1 | Version scope | One shared `schema_version` across request, response, error; all become 1.1.0 | Response-only bump | Contract README: "a producer must send ..., a consumer must reject any other value"; backend checks the request version before the schema (`backend-api.md` step 3); Brief R1 resolved. README's "error body is additive, stays 1.0.0" sentence is rewritten |
| 2 | `run_info` required? | Optional, top level | Required | Old/other producers (mocks, `stub`) stay valid; brief decision 4 |
| 3 | Tokens | Four fields mirroring `Usage`; totals over `MetricsCollector.records` | Only input/output | Cache read/write change real cost; cheap to include |
| 4 | Retries | Count what the collector records: the final attempt's usage per call, including failed calls' last usage; earlier failed attempts are not counted | Instrument each attempt | `litellm_client.py` keeps only last-attempt `usage`; instrumenting is pipeline change (out of scope). Documented as lower bound |
| 5 | `cost_usd` | `sum(per-tier tokens x price)`; omitted if any used tier lacks a price | 0 or null when unknown | Locked decision; no fake zeros |
| 6 | Price table home | `backend/src/iaudit_backend/pricing.py` (backend-owned); `backend/eval/prices.json` left as is | Move/shared JSON; backend reads eval file | Backend must not depend on `eval/`; leaving eval file avoids breaking `eval/run.py`, `score.py`, tests |
| 7 | Prompt hash | sha256 of file bytes, 16 hex, keys `atomize`, `link`, `check`, `prep` | Full 64 hex; `sha256:` prefix | Matches existing manifest, so eval and recordings compare directly; pattern-checked in schema |
| 8 | When emitted | Only when ≥1 LLM call recorded | Always (zeros) | A zero-token block in stub mode misleads cost totals |
| 9 | ADR | Add ADR 0014 "run_info is optional; one shared contract version" (decisions README lists one-line decisions with reasons; 0010 shows contract choices get ADRs) | No ADR | Shared-version rule and price ownership are non-obvious |

## Manual steps
- Owner confirms the price numbers in `pricing.py` (they start as the same unverified estimates as `eval/prices.json`: haiku 1/5, sonnet 2/10, opus 4/20 $/Mtok).

## Risks / Open Questions
- [RESOLVED: one shared version; see Decision 1] Request vs response bump (brief R1).
- [RESOLVED: recordings empty] `backend/eval/recorded/README.md` says it is "empty until the first live pass" [verified: only README present]; fixture keys hash `tier|call_tag|prompt` (`fixture_client.py:37`), not the version. ADR 0013 replay and nightly (`--mode oracle`) are unaffected. Re-run both to confirm.
- [OPEN] Does LiteLLM's `prompt_tokens` for Anthropic already include cache read/write tokens? If yes, pricing `input` at full rate plus cache fields double-counts. Blocks the cost formula in `pricing.py`. Cheapest test: one live call with a cached prefix, compare `prompt_tokens` to `cache_read_input_tokens`.
- [DEFERRED] Share one hash/price implementation between backend and `backend/eval` (touches ADHD harness; not requested).
- [DEFERRED] Per-attempt token accounting for retried calls (cost is a lower bound until then; B2 shows cost as "approx").
- [RESOLVED: B2/B3 handle] Mixed-version run (backend restarted mid-run with different prompts): B2 compares hashes across items; B1 only guarantees stability per process.
- [RESOLVED: ADR numbers] B1 takes ADR 0014; A1 uses 0015 (see `taxonomy-v1-20261020/01-taxonomy-v1/PRD.md`). Last existing ADR is 0013 [verified].
- Later bump: A1 moves the shared version 1.1.0 to 1.2.0 the same way (backend + frontend + validators + docs together). Items saved under 1.1.0 then fail the frontend pin in the eval item view (see A1 Risks, D2 R7).
- User decisions recorded here: `cost_usd` optional and omitted when no price (Req 5, Decision 5); a version bump moves backend, frontend and validators together (Decision 1).

## Acceptance Criteria
- `grep -rn '"1\.0\.0"'` over `docs/contracts docs/examples backend/src backend/eval frontend/src` finds no contract version occurrence (historical ADR text excepted).
- `docs/contracts/examples/response.json` includes `run_info`; `partial.response.json` and one mock response omit it; all validate against the 1.1.0 schema; `docs/examples/mock/validate.py` passes.
- A response with `schema_version: "1.0.0"` is rejected by backend (`unsupported_version`, 400) and frontend (`wrong_version`); a 1.1.0 response with and without `run_info` renders identically in the Audit view.
- Schema rejects `run_info` with transcript-like extra keys, negative `cost_usd`, or a non-16-hex hash.
- Backend test (fixture LLM): response `run_info.models` equals configured ids, token totals equal the sum of `snapshot()["records"]`, `cost_usd` present for priced models and absent when a model id has no price entry.
- Same prompt files yield identical `prompt_hashes` in two processes; editing one few-shot file changes only that stage's hash.
- Sentinel transcript word never appears in the serialised `run_info`.
- `uv run pytest`, `ruff check`, `npm run typecheck`, `npm test`, and `python -m eval.run --mode oracle --gate poc` all pass; `backend/eval` tests untouched except version strings.
- Contracts README, `backend-api.md`, `review-ui.md`, pre-release checklist and ADR 0014 updated in the same commit as the schemas.
