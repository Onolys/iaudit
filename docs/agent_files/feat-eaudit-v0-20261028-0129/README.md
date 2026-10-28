---
status: approved
summary: Index of the four approved PRDs for eaudit v0 (rename + utils + retry + Haiku 5.5, contract 0.0.1, taxonomy v2, docs pass), with locked decisions, risks and owner steps.
date: 2026-10-28
---
# eaudit v0 initiative (branch `feat/eaudit-v0`)

## Sub-projects
| # | Folder | Title | Depends on | Phase | Scope |
|---|---|---|---|---|---|
| 01 | [01-eaudit-rename-utils](01-eaudit-rename-utils/PRD.md) | eaudit rename, utils, retry wrapper, Haiku 5.5 | none | 1 | `backend/`→`eaudit/`, package `eaudit`, datasets under `eval/datasets/eaudit/` with `product` field, `utils/` + retry (py+ts), tab registry, Haiku 5.5, delete `.party/` |
| 02 | [02-contract-v0-0-1](02-contract-v0-0-1/PRD.md) | Contract v0.0.1 | 01 | 2 | All schemas `0.0.1`, 17-type enum + `group`, optional `speaker`, new error body with detail codes, ADR 0016 |
| 03 | [03-taxonomy-v2](03-taxonomy-v2/PRD.md) | Taxonomy v2 | 02 | 3 | Detect 4 new types, narrow 3, TofuEval mapping rewrite, mission to 17 checks / 4 groups |
| 04 | [04-docs-pass](04-docs-pass/PRD.md) | Docs pass | 03 | 4 | New concept pages, Mermaid, stage pages, contracts README, `eaudit-api.md` rename |

## Dependency graph
01 → 02 → 03 → 04 (sequential; each touches files the next builds on).

## Locked decisions
- Naming: folder `eaudit/`, package `eaudit`, doc `docs/reference/eaudit-api.md`, datasets `eval/datasets/eaudit/`; `IAUDIT_*` env vars, `iaudit_eval`, `eval/` kept (umbrella); `paudit` is a future product.
- Versioning: all schemas `"0.0.1"`; not deployed; no legacy/back-compat code, version history or migration; non-conforming files show a validation error and the owner deletes them.
- 17 concern types in 4 groups (not_in_interview, opposite_of_interview, changed_detail, missing_context); order 14-17 = opinion_as_fact, calculation_error, meaning_shift, unsupported_inference; SP03 Requirements 2 and 5 are the single source.
- `speaker` optional; missing = unknown, never invented; single `ambiguous_speaker` warning; unknown-speaker turns skipped in Q/A pairing; prompts render "unknown".
- Error body: `{schema_version, request_id?, status, message, details[{code,message}]}`, `details` minItems 1; `rate_limited` reserved.
- Retry wrapper: one `retry()` per language; callers keep request building and fallbacks; fixture keys unchanged. Frontend: audit POST retried only on HTTP 429 (never 503, 500, other statuses, network timeout or the 120 s deadline); eval idempotent GETs use it; decisions on HTTP status only.
- Cheap tier = `anthropic/claude-haiku-5-5` (owner confirms on first live run, not blocking).
- `.party/` folder deleted.
- Eval dataset metadata and `GET /datasets` gain `product` (only "eaudit"); UI groups by it.
- Docs pass runs after code lands.

## Cross-cutting risks / deferred
- TofuEval baseline/before/after/test runs: [DEFERRED: owner runs TofuEval later, outside this initiative]; no merge gated on them.
- opinion_as_fact vs certainty_inflation boundary: mitigated by fictional few-shot; measurement deferred to owner.
- PriMock57 omission/completeness check: parked as future (documented in research.md only).
- Prompt changes invalidate recorded LLM fixtures (ADR 0013); re-recording needs API keys (owner).
- More flags may raise false positives; prompt growth vs deadline.
- Docs drift if SP01-03 change late; docs start only after merge.

## Owner manual steps
- Recreate venvs after the rename (`rm -rf eaudit/.venv && cd eaudit && uv sync`; `eval/.venv` if needed); update aliases, IDE configs, CI required-check names (job `backend` → `eaudit`).
- Delete saved request/response/eval-run files at old versions.
- Confirm Haiku 5.5 id on first live run.
- Approve mission wording (17 checks, 4 groups) before SP03 code lands.
- Re-record LLM fixtures (needs API keys) after SP03 prompt changes.
- Review concerns-and-groups examples and research.md paper claims before SP04 merge.
- Run TofuEval later, outside this initiative (optional).

## SP03 completion

Taxonomy v2 is complete and independently reviewed: bugs, architecture and security all PASS after review fix `98ad587`. See [completed tasks](03-taxonomy-v2/TASKS.md), [implementation run summary](03-taxonomy-v2/code-2026-10-28-0545.md), [final review](03-taxonomy-v2/review-2026-10-28-0545.md), [acceptance evidence](03-taxonomy-v2/acceptance-2026-10-28.md) and [gold check](03-taxonomy-v2/gold-check-2026-10-28.md). SP03 owner/deferred work is recorded in the run summary.
