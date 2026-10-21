---
status: draft
summary: Six tasks to add optional run_info and move the whole contract, backend, frontend, examples and docs to 1.1.0 in one change.
date: 2026-10-20
---
# Tasks: B1 Contract run_info (1.1.0)

Source of truth: [PRD.md](PRD.md). One shared contract version bump to 1.1.0 plus an optional `run_info` block (models, prompt hashes; optional token/cost fields the backend never fills). All tests are offline (fixture LLM, oracle mode); no live calls. Tasks 1-5 land on one branch; the suite is only expected fully green from Task 5 onward, and Task 6 is the final gate.

| # | Task | Depends on | Status |
|---|---|---|---|
| 1 | Schemas 1.1.0 + `run_info` + contract examples and README | none | done |
| 2 | Backend version bump (src, tests, `backend/eval` pins) | 1 | done |
| 3 | `run_info` builder, attach in `app.py`, backend tests | 2 | done |
| 4 | Frontend 1.1.0 pin, types, fixtures | 1 | done |
| 5 | Examples, reference docs, checklist, ADR 0014 | 1, 3, 4 | done |
| 6 | Full offline verification | 2, 3, 4, 5 | done |

## Task 1 — Schemas 1.1.0 + run_info
What it is / what it means: The contract is the single source of truth, so it moves first (Req 4-6, Decisions 1, 2, 7).
What changes at a high level: All three schemas change `schema_version` to `1.1.0`. `audit-response` gains optional top-level `run_info`: required `models` (cheap/mid/strong strings) and `prompt_hashes` (atomize/link/check/prep, 16-hex pattern); optional non-negative integer token fields and `cost_usd`; all inner objects `additionalProperties:false`. Update the contract examples (`response.json` carries `run_info`, `partial.response.json` omits it) and rewrite the README, including the "error body stays 1.0.0" sentence.
Done when: every contract example validates; schema rejects extra keys in `run_info`, negative `cost_usd`, a non-16-hex hash; accepts `run_info` without token/cost fields.

## Task 2 — Backend version bump
What it is / what it means: The backend and its harness must say and enforce 1.1.0 (Req 6, Decision 1).
What changes at a high level: Change the version literal at the five `backend/src` sites, the `pyproject.toml` description, the four named backend tests, `backend/eval/adhd.py`, and the version string only in the pinned ADHD request files (transcript sha pins untouched). Add or adjust a test that a `1.0.0` request returns `unsupported_version` (400).
Done when: backend tests pass apart from `run_info` work; `backend/eval` tests untouched except version strings.

## Task 3 — run_info builder and attach
What it is / what it means: Gives the eval provenance over plain HTTP without leaking text (Req 1-3, Decisions 3, 5, 7, 8).
What changes at a high level: New `run_info.py` with `build(settings)` returning models and cached prompt hashes using the same algorithm as `backend/eval/run.py::prompt_hashes`. Attach in `app.py` after the pipeline and before response validation, only for the `full` pipeline; assembler stays pure. `AuditResponse` gets an optional `run_info`. Tokens and cost are never populated. Tests: models equal configured ids, token/cost absent, schema accepts them if present, stub omits `run_info`, hashes stable across two processes, editing one few-shot file changes only that stage hash, and extend sentinel test S9 to cover `run_info`.
Done when: those tests pass.

## Task 4 — Frontend 1.1.0
What it is / what it means: The UI must accept only 1.1.0 and tolerate `run_info` without showing it (Req 6, 7).
What changes at a high level: `types.ts` adds `run_info?: RunInfo` and sets both literals to `1.1.0`; `validate.ts` compares to `1.1.0`. Update the nine test/fixture files; no component reads `run_info`. Add tests for `wrong_version` on 1.0.0 and for identical rendering with and without `run_info`.
Done when: `npm run typecheck` and `npm test` pass.

## Task 5 — Examples, docs, ADR 0014
What it is / what it means: Everything user-facing moves with the schemas in the same change (Req 6, Decision 9).
What changes at a high level: Update `docs/examples/mock` (requests, responses, `validate.py` VERSION, README; one mock response omits `run_info`), `docs/examples/real` requests, `examples/{README,curl}`, `reference/{backend-api,review-ui}`, `testing/pre-release-checklist`, and `backend/README`. Add ADR 0014 "run_info is optional; one shared contract version" and list it in the decisions README. Leave historical mentions (ADR 0010, `limits-of-an-audit`).
Done when: `docs/examples/mock/validate.py` passes and the grep for contract-version `"1.0.0"` is clean outside historical ADR text.

## Task 6 — Full offline verification
What it is / what it means: Confirms the acceptance criteria end to end without live calls.
What changes at a high level: No new features; fix any residue. Run the grep over `docs/contracts docs/examples backend/src backend/eval frontend/src`, then `uv run pytest`, `ruff check`, `npm run typecheck`, `npm test`, and `python -m eval.run --mode oracle --gate poc`.
Done when: all commands pass and `ci.yml` / `nightly.yml` remain untouched.

## Owner manual checks
- If live recordings exist under `backend/eval/recorded/`, run the ADR 0013 replay against them (currently empty, so likely nothing to do).
- Any live-LLM smoke run of the `full` pipeline to eyeball `run_info` in a real response.
