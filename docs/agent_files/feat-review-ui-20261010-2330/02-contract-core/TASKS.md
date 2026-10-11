---
status: draft
summary: Four tasks: types and validators, bounds/code-point/span-walk, analysis and evidence ordering, excerpt chunks and public index.
date: 2026-10-10
---
# Tasks: 02 Contract core

Source of truth: docs/agent_files/feat-review-ui-20261010-2330/02-contract-core/PRD.md. A pure TypeScript layer in `frontend/src/contract/` (no React/DOM/fetch) that validates request and response, checks span bounds, and produces render data. Tests are Vitest in node env with inline fixtures.

| # | Task | Depends on | Status |
|---|---|---|---|
| 1 | Types and Ajv validators | 01/T1, 01/T3 | todo |
| 2 | Code points, bounds check, span walk | 1 | todo |
| 3 | Response analysis and evidence ordering | 2 | todo |
| 4 | Excerpt chunks and index export surface | 3 | todo |

## Task 1 — Types and Ajv validators
What it is / what it means: Typed, validated entry points for request and response (R1, R2; Decisions 1, 2, 4, 7-9).
What changes at a high level: Hand-write the contract types and `as const` enum arrays (re-exporting `Verdict`/`EvidenceRole` from SP01 tokens). Build one module-level `Ajv2020` with the PRD's options and no `ajv-formats`, compiling both schemas via `@contracts`. Implement `validateRequest` and `validateResponse` returning `Result`, with `ResponseError` kinds checked in order: not_object, wrong_version, schema, request_id_mismatch (only if the request has an id), duplicate_claim_id. Ajv messages stay raw.
Done when: the example pair validates; tests cover wrong version, non-object, schema path/message, id mismatch (and request without id), duplicate ids, and a mutated `contradicted` claim lacking contradicting evidence failing.

## Task 2 — Code points, bounds check, span walk
What it is / what it means: Position math, the one thing the schema cannot express (R3-R5; Decisions 3, 6).
What changes at a high level: Add `codePointLength` and `sliceCodePoints` (end exclusive). Add the span-validity check per the R3 table (index, strict lexicographic order, claim within one section, start/end char limits). Add `walkSpan` returning segments (single item, cross-turn with full middle turns including empty ones) that throws `RangeError` on invalid spans, and the defensive `segmentSection` partition into plain/claim pieces where an overlapping claim is rendered plain. Text only comes from slicing the request.
Done when: tests cover every R3 pass/fail row (including `end.char === len` ok, `start.char === len` fail, empty-turn start fail) and a cross-turn walk with an empty middle turn.

## Task 3 — Response analysis and evidence ordering
What it is / what it means: Per-claim flags, counts and navigation order (R6, R7 orderEvidence; Decision 3).
What changes at a high level: Implement `analyzeResponse` producing `orderedClaims` (stable sort by section, start, end; invalid spans last in response order), per-claim `ClaimCheck` (a bad span flags that claim only), and overall/by-section verdict counts including span-flagged claims. Add `claimIdsFor`, `notProcessedSections`, and `orderEvidence` splitting placed (sorted) from unplaceable evidence.
Done when: the example pair gives 5 claims, counts 1 each, no flags, and `claimIdsFor(a,'contradicted','all')` equals `['c-contradicted']`; a bad claim span and a bad evidence span each flag only their own claim; ordering tests pass.

## Task 4 — Excerpt chunks and index export surface
What it is / what it means: GitHub-style expansion data plus the single import surface for SP03-05 (R7 buildChunks, Architecture export table).
What changes at a high level: Implement `buildChunks` with a step of 3, clamping, merge of overlapping or touching ranges, each turn appearing once (shared turns carry both highlights), top/bottom excerpt ids and hidden counts. Create `index.ts` exporting exactly the names in the PRD export table.
Done when: chunk tests cover separate, touching, overlapping, clamped at both ends, shared turn, repeated expansion, and no duplicate turn; typecheck is clean; `src/contract/` imports no React/DOM/fetch; `docs/contracts/` is unchanged.
