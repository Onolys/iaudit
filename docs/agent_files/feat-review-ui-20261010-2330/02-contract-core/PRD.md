---
status: draft
summary: Pure TypeScript contract layer (types, Ajv validators, post-checks, code-point span walking, verdict counts/navigation, excerpt expand/merge) with unit tests; no React.
date: 2026-10-10
---
# PRD: 02 Contract core

Repo/branch: iaudit / `feat/review-ui` · Depends on: 01-frontend-scaffold · Owns: `frontend/src/contract/` (+ colocated `*.test.ts`)

## TL;DR
A framework-free library that turns raw JSON into trusted, positioned data: validate request/response with Ajv against the in-place schemas, run the checks the schema cannot express, slice text by Unicode code points, walk cross-turn spans, count and order claims, and compute merged excerpt chunks for GitHub-style expansion. SP03/04/05 consume it; none of them re-implement span math.

## Problem
Every visible highlight and quote is a position into the uploaded input. A single off-by-one or UTF-16/code-point mix-up silently shows the wrong words, which the mission forbids ("never display a quote not produced by slicing the uploaded input"). The schema cannot catch out-of-range spans; the consumer MUST. This logic must be correct, pure, and unit-tested before any UI exists.

## Goals / Non-Goals
**Goals**
- One validated, typed entry point for request and response, with typed errors the UI can map to screens.
- Per-claim span-bounds verdict: a bad span flags **that claim only**.
- Code-point slicing and the contract's "How to read a span" walk.
- Verdict counts (overall + per section), ordered claim lists for ‹ n of N › navigation.
- Pure excerpt expansion/merge; evidence ordering by transcript position.

**Non-Goals**
- React, DOM, fetch, file reading, JSON text parsing (SP03), colours/icons (SP01 tokens), app state (SP04).
- Re-checking rules the response schema already enforces (2-6, 11).
- Checking rule 9 (no copied text; unverifiable) or `explanation` wording.
- Any contract change; grapheme-cluster segmentation.

## Requirements

**R1 Types** (`types.ts`): hand-written `AuditRequest`, `Turn`, `Section`, `AuditResponse`, `Claim`, `Evidence`, `Concern`, `Warning`, `Span`, `Pointer`. Enum lists are `as const` arrays (`VERDICTS`, `CONCERN_TYPES`, `EVIDENCE_ROLES`, `WARNING_CODES`, `STATUSES`) with unions derived from them, except `Verdict` and `EvidenceRole`, which are defined in SP01 tokens and re-exported here (SP01 D8); `VERDICTS`/`EVIDENCE_ROLES` are typed against them. A **drift test** asserts each array equals the matching `enum` in the imported schema (same order; concern order = mission checks 1-12).

**R2 Validators** (`schemas.ts`, `validate.ts`): one module-level `Ajv2020` instance (`ajv/dist/2020`; both schemas declare `https://json-schema.org/draft/2020-12/schema` [verified]) compiling both schemas imported via `@contracts`. Options: `allErrors: true, allowUnionTypes: true, strictTypes: false`; leave `strictSchema` default (unknown keywords still fail). `ajv-formats` not needed (no `format` keyword [verified]). Schemas use only internal `#/$defs` refs, no cross-file `$ref`, relative `$id`s that do not collide [verified].
- `validateRequest(raw: unknown): Result<AuditRequest, ValidationIssue[]>`
- `validateResponse(raw: unknown, request: AuditRequest): Result<ValidatedResponse, ResponseError>`
- `ValidationIssue = { path: string; message: string }`. `path` from `instancePath` rendered as `/transcript/2/text` (root = `/`); for `required`/`additionalProperties` the missing/extra property is appended. Drop `if`-keyword errors ("must match then schema"), dedupe identical path+message, keep Ajv order.
- `ResponseError` discriminated by `kind`, in **check order**:
  1. `not_object` (non-object body)
  2. `wrong_version` (`schema_version !== "1.0.0"`; run **before** schema validation so the UI can show a distinct message rather than a generic `const` error)
  3. `schema` (+ `issues`)
  4. `request_id_mismatch` (+ `expected`, `received`)
  5. `duplicate_claim_id` (+ `id`) - see D4
  Never returns a partially valid response (contract: "do not render half an audit").

**R3 Bounds + claim analysis** (`analysis.ts`): `analyzeResponse(request, response): ResponseAnalysis`. Per claim a `ClaimCheck = { spanOutOfRange: boolean; issues: SpanIssue[]; evidence: Record<evidenceIndexOrId, {ok: boolean; issues}> }` where `SpanIssue.code` ∈ `index_out_of_range | start_not_before_end | claim_crosses_sections | start_char_out_of_range | end_char_out_of_range | end_at_turn_start | overlaps_claim`. Rules (units = code points; `len` = code-point length of the target item):
| Check | Pass condition |
|---|---|
| Index | `0 <= start.index <= end.index < count` (sections for claims, turns for evidence) |
| Order | `(start.index, start.char) < (end.index, end.char)` lexicographic, strictly |
| Claim one section | `start.index === end.index` |
| Start char | `0 <= start.char < len(start item)` (start must be **inside**; an empty turn can therefore never start a span) |
| End char | `0 <= end.char <= len(end item)` (end may equal len; exclusive) |
| Cross-turn end | if `end.index > start.index`, `end.char >= 1` (README: never `char: 0` on the end turn) |
| Overlap (claims) | no two claims in one section share a code point; nested counts as overlap |
`spanOutOfRange` for a claim = its own span fails **or** any of its evidence spans fails. Other claims are unaffected. Claim-span failure means no underline; evidence failure means only that excerpt is withheld; both set the badge flag. Overlap: sort a section's valid claims by `(start.char, end.char)`; the earlier keeps its place, each later overlapping claim gets `overlaps_claim` (so left-pane underlines stay flat).

**R4 Code points** (`codepoints.ts`): `codePointLength`, `sliceCodePoints(text, start, end)` = `Array.from(text).slice(start, end).join("")` (end exclusive), cached per request via a `WeakMap<AuditRequest, {turns: string[][]; sections: string[][]}>` so long assessments are not re-split per call. Pure; never mutates input.

**R5 Span walk** (`spans.ts`): `walkSpan(request, span, source: 'assessment' | 'transcript'): Segment[]` implementing README steps 1-3. `Segment = { index; from; to; length; text }` where `[from,to)` is the highlighted code-point range inside a turn of `length` (the UI dims `[0,from)` and `[to,length)`). Single item: one segment `[start.char,end.char)`. Cross-turn: start turn `[start.char,len)`, every strictly-between turn `[0,len)` in full (empty turns yield a zero-width segment so the header still renders), end turn `[0,end.char)`. Precondition: span passed the R3 check; otherwise throws `RangeError` (callers must gate on `spanOutOfRange`). `text` is only ever produced by slicing the request.
- `segmentSection(request, sectionIndex, claimChecks): Piece[]` where `Piece = {kind:'plain'|'claim'; from; to; text; claimId?}` partitions a section into plain gaps and valid, non-overlapping claims in order (consumed by SP04 for underlines; lives here because overlap/invalid handling is defined here).

**R6 Counts and navigation** (`analysis.ts`): `ResponseAnalysis.counts = { overall: Record<Verdict,number>; bySection: Record<number, Record<Verdict,number>> }` (every section index present, zeros included; a claim whose section index is out of range counts in `overall` only). All claims count, including span-flagged ones (the verdict is valid). `orderedClaims`: sorted by `(section index, start.char, end.char)`, stable on response order; claims with an invalid span sort last, in response order. `claimIdsFor(analysis, verdict, scope: 'all' | number): string[]` returns ids in that order, feeding SP04's `nav.claimIds`. Also `notProcessedSections(response): Set<number>` from `section_not_processed` warnings (unknown indexes ignored).

**R7 Excerpts** (`excerpts.ts`):
- `orderEvidence(request, claim, checks): OrderedEvidence[]` - valid evidence sorted by `(start.index, start.char, end.index, end.char)`, stable; flagged evidence returned separately as `unplaceable` (note/role still available, no text).
- `buildChunks(input): Chunk[]` pure. Input: `transcriptLength`, `excerpts: {id, firstTurn, lastTurn}[]` (from R5), `expansion: Record<id, {up: number; down: number}>` (click counts, SP05 owns state), `step = 3`. Each excerpt's visible range = `[max(0, first - 3*up), min(n-1, last + 3*down)]`. Ranges are sorted and **merged when they overlap or touch** (`next.start <= prev.end + 1`). Output chunks in transcript order:
```ts
Chunk { startTurn; endTurn;
  rows: { turn: number; highlights: { excerptId; from; to }[] }[]; // each turn once; [] = context row
  topExcerptId; bottomExcerptId;    // excerpts whose up/down a click on this chunk's edge increments
  hiddenAbove: number; hiddenBelow: number } // turns between prev chunk (or 0 / end) and this chunk
```
No turn appears in two chunks or twice in a chunk. A turn covered by two excerpts carries both highlights. `topExcerptId` = first excerpt by start, `bottomExcerptId` = excerpt with greatest end. A gap control between chunks maps to prev `bottomExcerptId.down` and next `topExcerptId.up`. Clamped at transcript bounds (extra clicks are no-ops; `hidden*` = 0 hides the control). No expand-all.

**R8 Tests** (Vitest, node env): example pair (valid request/response, all 5 verdicts, counts 1 each, section 0 only); every R3 row pass/fail incl. `end.char === len` ok, `start.char === len` fail, empty-turn start fail, cross-turn `char: 0` end fail; **emoji**: `"hi👍 ok"` where `text.slice` and code-point slice differ - assert highlights land on `👍` for start 2 / end 3, and that a later claim after the emoji is not shifted; cross-turn walk with an empty middle turn; wrong version, non-JSON-object, schema error path formatting, request_id mismatch (incl. request without id -> response id ignored), duplicate claim ids; overlap + nesting flagged; ordering with out-of-order response claims; `buildChunks`: separate, touching, overlapping, clamped at both ends, two excerpts sharing a turn, repeated expansion, never a duplicate turn. Mutating a deep-cloned example (e.g. `verdict: contradicted` with no contradicting evidence) must fail schema validation. Fixtures are inline in tests; `docs/contracts/examples/` is only read, never edited (new example pairs: SP06).

## Architecture
```
raw JSON --validateRequest--> AuditRequest
raw JSON --validateResponse(raw, request)--> {response}  (version -> schema -> request_id -> dup ids)
        --analyzeResponse(request, response)--> ResponseAnalysis
            { orderedClaims, checks[claimId], counts, notProcessed }
claim + request --walkSpan / orderEvidence / buildChunks--> render data
```
`index.ts` is the only import surface for other sub-projects. Consumers:
- **SP03** `validateRequest`, `validateResponse`, `ResponseError.kind` -> error screens; `notProcessedSections`, `response.warnings` for banner.
- **SP04** owns app state `{request, response, selectedClaimId, nav: {verdict, scope: 'all'|sectionIndex, claimIds, position} | null}`; calls `analyzeResponse`, `claimIdsFor`, `segmentSection`, `counts`.
- **SP05** renders `ClaimDetail({claim, request, check: ClaimCheck})`; calls `walkSpan`, `orderEvidence`, `buildChunks`. SP04 passes `check` = `analysis.checks[claim.id]`; `check.spanOutOfRange` is the boolean.

Verified in a scratch project: `new Ajv2020({})` logs strictTypes warnings (`contains`/`minItems` without `type`) and **`strict: true` throws** on the response schema (union type on `score`; `if/then` bodies without `type`; with `strictRequired` on, `then: {required}` too). The chosen options validate the example pair true and a `contradicted` claim without contradicting evidence false. `[verified: ajv 8 run 2026-10-10]`

## Decisions
| # | Decision | Choice | Alternatives considered | Why |
|---|---|---|---|---|
| 1 | Ajv build | `ajv/dist/2020`, strictTypes off, union types on | `strict:true` (throws); default (console noise); edit schemas | Schemas are contract-owned and untouchable; keep unknown-keyword strictness |
| 2 | Types | Hand-written + enum drift test | `json-schema-to-typescript` codegen | `if/then` schemas generate poor types; no build step; drift test catches the real risk |
| 3 | Bounds failure scope | Per-claim flag (claim span or any evidence span) | Reject whole response | Contract consumer rule: render the claim with a warning badge |
| 4 | Duplicate claim id | Reject response (`duplicate_claim_id`) | Tolerate, index keys | Selection, nav, and warnings key on id; ambiguity would mis-select silently |
| 5 | Unknown `evidence_ids`, duplicate evidence ids, bad `section_index`/`claim_id` in warnings | Tolerate; ignore dangling refs | Reject | Cosmetic; mission forbids hiding the audit over a bad cross-ref |
| 6 | Rule 8 overlap | Check; flag later overlapping claim | Trust; reject | Overlap breaks flat underlines and `segmentSection`; flag is local and cheap |
| 7 | Cross-turn `end.char === 0` | Flag as invalid | Tolerate (harmless) | README rule 1 says MUST not; also guards against the empty-turn edge |
| 8 | `request_id` | Mismatch only if the request has one and response differs/omits; ignore otherwise | Always require equality | Contract: echoed "when sent" |
| 9 | Version check order | Before schema | Rely on schema `const` | Distinct, clear error for a wrong version |
| 10 | Code-point cache | `WeakMap` keyed by request object | Memoize on strings; pre-split in state | Callers pass the plain request; no hidden state in SP04 |
| 11 | Rules 2-6, 11 | Trust schema | Re-check | Already enforced by the response schema [verified: if/then in schema] |
| 12 | Rules not checkable | 9 (copied text) and 12 (wording): not checked | Heuristic text matching | False positives; reviewer judges |
| 13 | Request id uniqueness (turn/section ids) | Not checked | Check | UI keys on indexes; ids are logs only |

## Risks / Open Questions
- [RESOLVED: lexicographic pointer compare, strict start<end] Empty or zero-width span is invalid.
- [RESOLVED: flag only] One bad span never shifts or hides other claims.
- [OPEN] Two evidence excerpts sharing a turn with different roles: `buildChunks` returns both highlights; how SP05 paints overlapping ranges (split by boundary? stack borders?) is undecided.
- [OPEN] Lone surrogates in input text: `Array.from` yields them as one unit while Python rejects/encodes them differently, so offsets could disagree with the backend. Likely out of practical scope; confirm with backend.
- [OPEN] ZWJ/combining sequences are several code points; a span may cut mid-grapheme (contract defines code points, so we follow it). Cosmetic only; confirm acceptable.
- [OPEN] Friendly wording for Ajv messages on `contains`/`minContains` failures ("must contain at least 1 valid item(s)"): raw message ships here; SP03 may map by path.
- [OPEN] Performance ceiling for very long transcripts (thousands of turns): R5 caching assumed enough; measure on SP06's long fixture.
- [OPEN] Interface gaps found by consumers (SP03/04/05): (a) element type of `ResponseAnalysis.orderedClaims` (SP04 assumes `Claim[]`; the Architecture sketch lists it without a type); (b) `ResponseAnalysis` is sketched with a `notProcessed` field while R6 defines `notProcessedSections(response)` as a function - pick one surface; (c) `ClaimCheck.evidence` key (`evidenceIndexOrId`) is ambiguous - SP05 keys by evidence `id`; (d) `orderEvidence(request, claim, checks)` third arg: SP05 passes one `ClaimCheck`, R7 names `checks`; (e) `ResponseAnalysis.checks` (used by SP04/05) is named only in the Architecture sketch, not in R3/R6.
- [DEFERRED] Whether `partial` + `section_not_processed` should also gate claims in that section; SP04.
- [DEFERRED] Export of warnings-to-claim join (`span_out_of_range` warnings from the backend vs our own bounds flag); SP03/04 decide the banner copy. Our flag is authoritative for rendering.

## Acceptance Criteria
- `npm test` passes all R8 cases; `npm run typecheck` and `lint` clean; `src/contract/` imports no React/DOM/fetch.
- Example pair: `validateRequest` ok; `validateResponse(raw, request)` ok; `analyzeResponse` gives 5 claims, no span flags, overall counts 1 each, `claimIdsFor('contradicted','all')` = `['c-contradicted']`.
- Emoji test fails if `walkSpan`/`sliceCodePoints` is swapped for `String.prototype.slice`.
- Out-of-range claim span, out-of-range evidence span, and overlap each flag **only** the offending claim; every other claim's `walkSpan` output is identical to the unflagged case.
- `validateResponse` returns distinct `kind`s for: version `"2.0.0"`, extra property, wrong `request_id`, duplicate claim ids.
- `buildChunks`: any turn index occurs at most once across all chunks; touching ranges merge; expanding by 3 per click matches the table of expected ranges in tests; clamped at index 0 and `n-1`.
- Drift test fails if a schema enum value is added without updating the TS arrays.
- `docs/contracts/` unchanged.
