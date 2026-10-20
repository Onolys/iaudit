---
status: draft
summary: Add optional run_info (models, prompt hashes; optional tokens/cost_usd that the backend does not populate) to AuditResponse and move the whole contract, backend, frontend, examples and tests to 1.1.0 in one change.
date: 2026-10-20
---
# PRD: B1 Contract run_info (1.1.0)

Repo/branch: iaudit / `users/codex/eval-investigation` · Depends on: none (first of B1 → B2 → B3 → B4 → C1 → C2 → D1 → D2 → A1) · Owns: `docs/contracts/` (3 schemas, README, examples), `docs/examples/{mock,real,README.md,curl.md}`, `docs/reference/{backend-api,review-ui}.md`, `docs/testing/pre-release-checklist.md`, new ADR 0014, `backend/src/iaudit_backend/{app.py,run_info.py,models/audit.py,api/errors.py,assembler/__init__.py}`, backend tests, `backend/eval/adhd.py` + `backend/eval/data/adhd/requests/*.json` (version string only), `frontend/src/contract/{types.ts,validate.ts}` + frontend tests

## TL;DR
Every successful audit response may carry `run_info`: model id per tier and prompt hashes. The contract also declares optional `input_tokens`/`output_tokens`/`cache_*_tokens` and `cost_usd` so consumers display them if a response carries them; the backend does not compute or populate them (no token accounting, no pricing). This is what lets the eval (B2+) record provenance over plain HTTP. The schema is one shared version, so the bump to **1.1.0** touches request, response and error schemas and every consumer at once. The Audit UI ignores `run_info`.

## Problem
- Models and prompts exist only inside the backend (`Settings.model_*`, prompt files). The eval cannot prove which prompts/models produced a run without importing backend code (forbidden by brief decision 2).
- Token/cost reporting is out of scope for the backend (owner decision 2026-10-20); the contract keeps the optional fields only so consumers can show them when present.
- All three schemas hard-code `const "1.0.0"` and consumers must reject anything else, so adding a field forces a coordinated bump.

## Goals / Non-Goals
**Goals**
- Optional `run_info` in AuditResponse; old 1.0.0-shaped bodies minus the version still validate structurally.
- Backend populates models and prompt hashes from live config; contains no transcript/assessment text. Optional token/cost fields are declared but never populated by the backend.
- 1.1.0 everywhere in one change; CI (`ci.yml`) and nightly (`nightly.yml`) stay green.
- `backend/eval` unbroken.

**Non-Goals**
- Displaying `run_info` in the Audit view.
- Any backend token accounting, pricing table or cost computation.
- Per-stage or per-call breakdowns, latency fields (Server-Timing already covers latency).
- Changing `backend/eval` price logic or `eval/run.py` hashing (hash consolidation is [DEFERRED]).
- Accepting both 1.0.0 and 1.1.0 (contract rule: reject any other value).
- Any pipeline/prompt change; `run_info` on error bodies.

## Requirements
1. A successful `POST /v1/audit` (pipeline `full`) returns `run_info`; omitted for the `stub` pipeline.
2. `run_info.models`: ids actually configured for `cheap`, `mid`, `strong`.
3. `run_info.prompt_hashes`: one hash per prompt group, stable across restarts and machines for identical files.
4. `run_info.input_tokens` / `output_tokens` / `cache_read_tokens` / `cache_write_tokens`: optional in the schema; the backend does not populate them. Consumers display them if present.
5. `run_info.cost_usd`: optional in the schema; the backend does not populate it. Consumers display it if present.
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
Required inside `run_info`: `models`, `prompt_hashes`. Optional (never populated by the backend): the four token fields (integers, `minimum: 0`) and `cost_usd` (number, `minimum: 0`). All inner objects `additionalProperties:false`.

**Backend data flow**
```
app._audit -> pipeline -> result.to_json() -> out
  + run_info.build(settings)   # new, after pipeline, before validate_response
  -> contract.validate_response(out) -> JSONResponse
```
- New `run_info.py`: `build(settings) -> dict | None`; `prompt_hashes()` computed once at import/startup and cached. Same algorithm as `backend/eval/run.py::prompt_hashes` (sha256 over file bytes of `*_system.md` + `*_fewshot.json`, first 16 hex; prep = hash of `prep.prompt.SYSTEM`) so values equal the recording manifest's.
- Assembler stays pure (does not know run_info). Attach in `app.py` so stub/fixture paths are handled in one place.
- `AuditResponse` pydantic model gets an optional `run_info`; `to_json` already drops `None`.
- PHI: `run_info` holds ids, hashes and counts only. No new log fields needed; existing `audit_request` log is unchanged. Sentinel test S9 (`tests/latency/test_latency.py`) extended to assert the sentinel never appears in `run_info`.

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
| 3 | Tokens | Optional contract fields; backend does not populate | Backend token totals | Owner decision 2026-10-20: drop backend token accounting |
| 4 | Retries | n/a (no token accounting) | - | Moot |
| 5 | `cost_usd` | Optional contract field; backend does not populate; no fake zeros | Backend pricing/cost | Owner decision 2026-10-20: drop backend pricing |
| 6 | Price table home | None: no `pricing.py`; `backend/eval/prices.json` left as is | Backend price table | Owner decision 2026-10-20 |
| 7 | Prompt hash | sha256 of file bytes, 16 hex, keys `atomize`, `link`, `check`, `prep` | Full 64 hex; `sha256:` prefix | Matches existing manifest, so eval and recordings compare directly; pattern-checked in schema |
| 8 | When emitted | Only for pipeline `full` | Always | A `run_info` block in stub mode would claim models/prompts that were not used |
| 9 | ADR | Add ADR 0014 "run_info is optional; one shared contract version" (decisions README lists one-line decisions with reasons; 0010 shows contract choices get ADRs) | No ADR | Shared-version rule and price ownership are non-obvious |

## Manual steps
- None. [RESOLVED: no `pricing.py`, so no price numbers to confirm, owner decision 2026-10-20]

## Risks / Open Questions
- [RESOLVED: one shared version; see Decision 1] Request vs response bump (brief R1).
- [RESOLVED: recordings empty] `backend/eval/recorded/README.md` says it is "empty until the first live pass" [verified: only README present]; fixture keys hash `tier|call_tag|prompt` (`fixture_client.py:37`), not the version. ADR 0013 replay and nightly (`--mode oracle`) are unaffected. Re-run both to confirm.
- [RESOLVED: moot, no backend cost, owner decision 2026-10-20] LiteLLM `prompt_tokens` vs cache tokens.
- [DEFERRED] Share one hash implementation between backend and `backend/eval` (touches ADHD harness; not requested). [RESOLVED: shared price code moot, owner decision 2026-10-20]
- [RESOLVED: moot, no backend token accounting, owner decision 2026-10-20] Per-attempt token accounting for retried calls.
- [RESOLVED: B2/B3 handle] Mixed-version run (backend restarted mid-run with different prompts): B2 compares hashes across items; B1 only guarantees stability per process.
- [RESOLVED: ADR numbers] B1 takes ADR 0014; A1 uses 0015 (see `taxonomy-v1-20261020/01-taxonomy-v1/PRD.md`). Last existing ADR is 0013 [verified].
- Later bump: A1 moves the shared version 1.1.0 to 1.2.0 the same way (backend + frontend + validators + docs together). Items saved under 1.1.0 then fail the frontend pin in the eval item view (see A1 Risks, D2 R7).
- User decisions recorded here: `tokens` and `cost_usd` optional and not populated by the backend (Req 4-5, Decisions 3, 5); a version bump moves backend, frontend and validators together (Decision 1).

## Acceptance Criteria
- `grep -rn '"1\.0\.0"'` over `docs/contracts docs/examples backend/src backend/eval frontend/src` finds no contract version occurrence (historical ADR text excepted).
- `docs/contracts/examples/response.json` includes `run_info`; `partial.response.json` and one mock response omit it; all validate against the 1.1.0 schema; `docs/examples/mock/validate.py` passes.
- A response with `schema_version: "1.0.0"` is rejected by backend (`unsupported_version`, 400) and frontend (`wrong_version`); a 1.1.0 response with and without `run_info` renders identically in the Audit view.
- Schema rejects `run_info` with transcript-like extra keys, negative `cost_usd`, or a non-16-hex hash; accepts one without token/cost fields.
- Backend test (fixture LLM): response `run_info.models` equals configured ids; token and cost fields are absent; schema accepts a `run_info` that carries them (consumer display only).
- Same prompt files yield identical `prompt_hashes` in two processes; editing one few-shot file changes only that stage's hash.
- Sentinel transcript word never appears in the serialised `run_info`.
- `uv run pytest`, `ruff check`, `npm run typecheck`, `npm test`, and `python -m eval.run --mode oracle --gate poc` all pass; `backend/eval` tests untouched except version strings.
- Contracts README, `backend-api.md`, `review-ui.md`, pre-release checklist and ADR 0014 updated in the same commit as the schemas.
