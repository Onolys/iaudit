---
status: draft
summary: Nine tasks resetting all schemas to 0.0.1 with no back-compat, then adding 17 types plus group, optional speaker and the redesigned error body across schemas, backend, frontend, eval, README and ADR 0016.
date: 2026-10-28
---
# Tasks: SP02 Contract v0.0.1

Source of truth: [PRD.md](PRD.md). One coordinated contract change with no migration, built on SP01's renamed layout (`eaudit/`, package `eaudit`). Detection of the four new types is SP03; explanatory prose is SP04. Agents run only offline checks (replay mode, no live calls).
Contract versioning rule: all schemas are `schema_version` `"0.0.1"`; the project is not deployed, so there is no legacy/back-compat code, version history or migration; a file or body not conforming to the current schema just shows a validation error and the owner deletes it.

Every task regenerates the examples and fixtures it touches, so each commit leaves the `eaudit/`, `eval/` and frontend suites green.

| # | Task | Depends on | Status |
|---|---|---|---|
| 1 | Version reset and back-compat deletion | SP01 | done |
| 2 | Eval schemas reset | 1 | done |
| 3 | 17 concern types and `group` | 1 | done |
| 4 | Group headings in the claim detail UI | 3 | in-progress |
| 5 | Optional speaker | 3 | todo |
| 6 | Backend error body and detail codes | 1 | todo |
| 7 | Frontend error handling | 6 | todo |
| 8 | Contract README tables and ADR 0016 | 3, 5, 6 | todo |
| 9 | Acceptance sweep | 1-8 | todo |

## Task 1 — Version reset and back-compat deletion
What it is / what it means: The versioning rule applied to the three contract schemas and every component that carries a version (R1, Decisions 1, 9).
What changes at a high level: The schema `const` becomes `0.0.1`; each component keeps one version literal. The step-3 version rejection, `unsupported_version` code, `wrong_version` load error and its screen text are deleted, so a wrong version surfaces as an ordinary schema violation. Version-history prose and request/response examples, mock fixtures and ADHD requests move to `0.0.1`.
Done when: no `1.0.0`, `1.1.0` or `1.2.0` contract string remains outside git history and `docs/agent_files/`, and all suites pass.

## Task 2 — Eval schemas reset
What it is / what it means: The eval side of the same rule (R10, Decision 1).
What changes at a high level: `metrics`, `item_rows` and `compare` schemas and the report literal move to `0.0.1`; hardcoded `1.0.0` in eval tests and fixtures is updated. The dataset metadata schema carries SP01's `product` field at `0.0.1` (SP02 owns the version, SP01 the field). Stored run files at old versions simply fail validation.
Done when: eval tests pass, and the oracle report test still lists only its gold buckets.

## Task 3 — 17 concern types and `group`
What it is / what it means: The taxonomy axis the UI summarizes by (R2, R3, Decisions 2-4). Enum order and the group map are copied exactly from SP03 Requirements 2 and 5.
What changes at a high level: Four enum values are appended in the response schema, `ConcernType` and `CONCERN_TYPES`. `concerns[].group` becomes required, enforced by four `allOf` if/then clauses. A single Python map module and a single TS map module are added; the assembler sets `group`; frontend labels gain the four new names. Examples, fixtures and eval buckets pick up the new values. A drift test per language compares its map to the schema.
Done when: the schema rejects a missing group, a mismatched group (one test per group) and a type outside the 17; both drift tests pass.

## Task 4 — Group headings in the claim detail UI
What it is / what it means: The reviewer-facing use of `group` (R8, Decision 10).
What changes at a high level: `ConcernList` groups a claim's concerns under the four group headings in the fixed order, omitting empty groups and keeping concern order within a group. No color tokens change; a group is a heading only.
Done when: component tests show grouping under the four labels in fixed order, and frontend typecheck and tests pass.

## Task 5 — Optional speaker
What it is / what it means: Real transcripts without labels are audited, never rejected or guessed (R4, Decisions 5, 6).
What changes at a high level: `speaker` leaves `Turn.required` in the schema, backend models and frontend type. Unknown-speaker turns are skipped in Q/A pairing, link validation and shortlist guards, the atomize roster, and the Group A attribution, question-as-answer and conflicting-accounts checks, counted so the assembler raises the single `ambiguous_speaker` warning with its new wording. Prompts render "unknown"; `ChunkView` shows "Unknown speaker". A no-speaker request/response example pair is added.
Done when: unit tests in `prep` and `check/group_a` pass, a speaker-free request returns 200 with the warning, and replay tests pass.

## Task 6 — Backend error body and detail codes
What it is / what it means: One error shape for every non-2xx path (R5, R6, Decisions 7-9).
What changes at a high level: The error schema becomes `{schema_version, request_id?, status, message, details[{code,message}]}` with `details` minItems 1 and the fixed 18-code enum, and the old `error` object and codes are removed. `ApiError` and `error_body` take status, message and details; the app chooses `empty_transcript`/`empty_assessment` or `schema_violation` (capped at 5), the CORS middleware uses `cors_rejected`, and the outcome log uses the first detail code. Error examples include a multi-error one.
Done when: a test per code (schema-only for `rate_limited`) shows the body validates, `status` equals the HTTP status, and bare framework errors carry a detail.

## Task 7 — Frontend error handling
What it is / what it means: The consumer side of the new error body (R7, Decision 8).
What changes at a high level: `readErrorMessage` becomes `readErrorBody`, returning status, message and details only when the body validates. `LoadError` http variants carry message and details; `ErrorScreen` shows the status title, message, then the details list. Invalid, HTML or old-shape bodies show generic status text. Retry stays status-based. Mock transport and error fixtures are updated.
Done when: tests cover a valid body, a non-JSON body and an old-shape body, and frontend suites pass.

## Task 8 — Contract README tables and ADR 0016
What it is / what it means: Normative documentation only; prose and diagrams stay with SP04 (R11, R12, Decision 11).
What changes at a high level: `docs/contracts/README.md` drops Versioning and Version history for a "Version `0.0.1`, no compatibility promise" line, and gains the speaker-optional request table, concern and concern-type tables with group column, `ambiguous_speaker` wording, and the error body plus detail-code table. `docs/reference/{backend-api,warnings}.md` get only lines that would now be false. ADR 0016 is added; 0011, 0014 and 0015 are edited and 0014/0015 are marked as amended by 0016.
Done when: README tables match the schemas, and ADR 0016 states the versioning rule verbatim.

## Task 9 — Acceptance sweep
What it is / what it means: Verification of PRD acceptance criteria 1-8, offline only.
What changes at a high level: Grep for old versions and deleted codes, validate every example with both `jsonschema` and Ajv, run `eaudit/`, `eval/` and frontend suites plus replay-mode CI to confirm LLM fixtures are untouched, and fix any regression.
Done when: all eight acceptance criteria hold.

## Owner manual steps (not tasks)
- Delete any saved request, response or eval run files at old versions; they will show validation errors.
- Mission wording for the new types is SP03; live evals and TofuEval runs are deferred to the owner outside this initiative.
