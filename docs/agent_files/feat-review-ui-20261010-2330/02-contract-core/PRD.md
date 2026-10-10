---
status: draft
summary: Pure TypeScript contract layer (types, Ajv validators, span-bounds check, code-point span walking, verdict counts/navigation, excerpt expand/merge) with unit tests; no React. Explicit export table for consumers.
date: 2026-10-10
---
# PRD: 02 Contract core

Repo/branch: iaudit / `feat/review-ui` · Depends on: 01-frontend-scaffold · Owns: `frontend/src/contract/` (+ colocated `*.test.ts`)

## TL;DR
A framework-free library that turns raw JSON into trusted, positioned data: validate request/response with Ajv against the in-place schemas, check span bounds (the one thing the schema cannot express), slice text by code points, walk cross-turn spans, count and order claims, and compute merged excerpt chunks for GitHub-style expansion. SP03/04/05 consume it; none re-implement span math.

## Problem
Every highlight and quote is a position into the uploaded input; the mission forbids showing a quote not produced by slicing it. The schema cannot catch out-of-range spans, so the consumer MUST. Input is normalized English text (no emoji); the contract defines offsets in code points, so we slice with `Array.from`.

## Goals / Non-Goals
**Goals**
- Validated, typed entry points for request and response with typed errors.
- Per-claim span-bounds flag: a bad span flags **that claim only**.
- Code-point slicing, span walk, verdict counts, ordered claims for nav, excerpt chunks.

**Non-Goals**
- React, DOM, fetch, file reading, JSON text parsing (SP03), colours (SP01), app state (SP04).
- Re-checking rules the schema enforces, or stricter-than-contract checks (claim overlap, cross-turn `end.char === 0`): trust the backend.
- Rule 9 (copied text), `explanation` wording, enum-drift tests, grapheme handling, emoji/astral edge cases, performance work.

## Requirements

**R1 Types** (`types.ts`): hand-written `AuditRequest`, `Turn`, `Section`, `AuditResponse`, `Claim`, `Evidence`, `Concern`, `Warning`, `Span`, `Pointer`. Enum arrays `as const` (`VERDICTS`, `CONCERN_TYPES` in mission check order 1-12, `EVIDENCE_ROLES`, `WARNING_CODES`, `STATUSES`) with derived unions; `Verdict`/`EvidenceRole` re-exported from SP01 tokens.

**R2 Validators** (`validate.ts`): one module-level `Ajv2020` (`ajv/dist/2020`) compiling both schemas via `@contracts`. Options: `allErrors: true, allowUnionTypes: true, strictTypes: false` (default `strictSchema`). No `ajv-formats`.
- `validateRequest(raw: unknown): Result<AuditRequest, ValidationIssue[]>`
- `validateResponse(raw: unknown, request: AuditRequest): Result<AuditResponse, ResponseError>`
- `Result<T,E> = { ok: true; value: T } | { ok: false; error: E }`
- `ValidationIssue = { path: string; message: string }` = Ajv `instancePath` (`/` for root) + raw Ajv `message`, shown as is (no prettifying).
- `ResponseError` (discriminated by `kind`), checked in this order: `not_object`; `wrong_version` (`schema_version !== "1.0.0"`, before schema validation); `schema` (+ `issues: ValidationIssue[]`); `request_id_mismatch` (+ `expected`, `received`; only when the request has an id and the response differs or omits it); `duplicate_claim_id` (+ `id`). Never returns a partial response.

**R3 Bounds check** (`analysis.ts`): units = code points. A span is valid iff:
| Check | Pass condition |
|---|---|
| Index | `0 <= start.index <= end.index < count` (sections for claims, turns for evidence) |
| Order | `(start.index, start.char) < (end.index, end.char)` lexicographic, strict |
| Claim in one section | `start.index === end.index` |
| Start char | `0 <= start.char < len(start item)` |
| End char | `0 <= end.char <= len(end item)` |
A bad claim span means no underline; a bad evidence span means only that excerpt is withheld (listed in `unplaceable`); either sets the claim's `spanOutOfRange`. Other claims are unaffected. No overlap or cross-turn-zero checks.

**R4 Code points** (`codepoints.ts`): `codePointLength(text)`, `sliceCodePoints(text, start, end)` = `Array.from(text).slice(start, end).join("")` (end exclusive). Pure, no cache.

**R5 Span walk** (`spans.ts`)
- `walkSpan(request, span, source: 'assessment' | 'transcript'): Segment[]`; `Segment = { index; from; to; length; text }` (`[from,to)` highlighted inside an item of `length`; UI dims the rest). Single item: one segment. Cross-turn: start turn `[start.char,len)`, strictly-between turns in full (empty turn = zero-width segment), end turn `[0,end.char)`. Throws `RangeError` if the span fails R3 (callers gate on `spanOutOfRange` / `unplaceable`). `text` only ever comes from slicing the request.
- `segmentSection(request, sectionIndex, checks: Record<string, ClaimCheck>, claims: Claim[]): Piece[]` where `Piece = { kind: 'plain'|'claim'; from; to; text; claimId?: string }` partitions the section into plain gaps and claims whose span is valid, in order. Defensive only: a claim starting before the previous claim's end is rendered as plain text (no throw, no duplicate text).

**R6 Analysis** (`analysis.ts`): `analyzeResponse(request, response): ResponseAnalysis`. Counts include every claim (span-flagged too). `orderedClaims` sorts by `(section index, start.char, end.char)`, stable; claims with an invalid span sort last in response order. `claimIdsFor(analysis, verdict, scope)` returns ids from `orderedClaims` (SP04 `nav.claimIds`). `notProcessedSections(response)` returns indexes from `section_not_processed` warnings (unknown indexes ignored).

**R7 Excerpts** (`excerpts.ts`)
- `orderEvidence(request, claim: Claim, check: ClaimCheck): { placed: Evidence[]; unplaceable: Evidence[] }`. `placed` = evidence with `check.evidence[ev.id] === true`, sorted by `(start.index, start.char, end.index, end.char)`, stable. `unplaceable` = the rest (note/role still usable, no text).
- `buildChunks({ transcriptLength, excerpts: {id, firstTurn, lastTurn}[], expansion: Record<id,{up,down}>, step = 3 }): Chunk[]`. Visible range per excerpt = `[max(0, first - step*up), min(n-1, last + step*down)]`; ranges sorted and merged when overlapping or touching (`next.start <= prev.end + 1`).
```ts
Chunk { startTurn; endTurn;
  rows: { turn: number; highlights: { excerptId; from; to }[] }[]; // each turn once; [] = context row
  topExcerptId; bottomExcerptId;   // excerpts whose up/down a click on this chunk's edge increments
  hiddenAbove: number; hiddenBelow: number }  // turns to prev chunk (or 0 / end)
```
No turn appears twice. A turn covered by two excerpts carries both highlights; **how overlapping highlights are painted (neutral highlight, no stripes) is owned by SP05**. `hidden* = 0` hides the control. Clamped at bounds. No expand-all.

**R8 Tests** (Vitest, node env, inline fixtures; `docs/contracts/examples/` read-only): example pair validates, 5 claims, counts 1 each, no flags; each R3 row pass/fail (incl. `end.char === len` ok, `start.char === len` fail, empty-turn start fail); out-of-range claim span / evidence span each flag only that claim; cross-turn walk with an empty middle turn; wrong version, non-object, schema error path/message, request_id mismatch (and request without id ignores response id), duplicate claim ids; a mutated clone (`contradicted` without contradicting evidence) fails schema validation; ordering with out-of-order response claims and invalid-span-last; `buildChunks`: separate, touching, overlapping, clamped at both ends, two excerpts sharing a turn, repeated expansion, no duplicate turn.

## Architecture
```
raw --validateRequest--> AuditRequest
raw --validateResponse(raw, request)--> AuditResponse   (version -> schema -> request_id -> dup ids)
(request, response) --analyzeResponse--> ResponseAnalysis
claim + request --walkSpan / orderEvidence / buildChunks / segmentSection--> render data
```
`index.ts` is the only import surface. **Export table** (names match SP03/04/05 usage):

| Export | Shape |
|---|---|
| `validateRequest(raw)` | `Result<AuditRequest, ValidationIssue[]>` |
| `validateResponse(raw, request)` | `Result<AuditResponse, ResponseError>` |
| `ValidationIssue` | `{ path: string; message: string }` |
| `ResponseError` | `{kind:'not_object'} \| {kind:'wrong_version'} \| {kind:'schema'; issues} \| {kind:'request_id_mismatch'; expected; received} \| {kind:'duplicate_claim_id'; id}` |
| `analyzeResponse(request, response)` | `ResponseAnalysis` |
| `ResponseAnalysis` | `{ orderedClaims: Claim[]; checks: Record<claimId, ClaimCheck>; counts: { overall: Record<Verdict,number>; bySection: Record<number, Record<Verdict,number>> } }` (every section index present, zeros included; a claim whose section index is out of range counts in `overall` only) |
| `ClaimCheck` | `{ spanOutOfRange: boolean; claimSpanOk: boolean; evidence: Record<evidenceId, boolean> }` (key = `Evidence.id`; `true` = placeable; `spanOutOfRange` = claim span bad or any evidence bad) |
| `claimIdsFor(analysis, verdict, scope: 'all' \| number)` | `string[]` |
| `notProcessedSections(response)` | `Set<number>` (function; not a field of `ResponseAnalysis`) |
| `segmentSection(request, sectionIndex, checks, claims)` | `Piece[]` |
| `walkSpan(request, span, source)` | `Segment[]` |
| `orderEvidence(request, claim, check)` | `{ placed: Evidence[]; unplaceable: Evidence[] }` (3rd arg = one `ClaimCheck`) |
| `buildChunks(input)` | `Chunk[]` |
| `sliceCodePoints`, `codePointLength` | string helpers |
| types + enum arrays | R1 |

Ajv notes `[verified: ajv 8 run 2026-10-10]`: default `new Ajv2020({})` logs strictTypes warnings and `strict: true` throws on the response schema; the chosen options validate the example pair true and a `contradicted` claim without contradicting evidence false.

## Decisions
| # | Decision | Choice | Alternatives | Why |
|---|---|---|---|---|
| 1 | Ajv build | `ajv/dist/2020`, strictTypes off, union types on | `strict:true` (throws); edit schemas | Schemas are contract-owned |
| 2 | Types | Hand-written | Codegen | `if/then` schemas generate poor types; no build step |
| 3 | Bounds failure scope | Per-claim flag | Reject whole response | Contract: render claim with warning badge |
| 4 | Duplicate claim id | Reject response | Tolerate | Selection/nav key on id |
| 5 | Dangling refs, duplicate evidence ids, bad warning indexes | Tolerate | Reject | Cosmetic |
| 6 | Overlap, cross-turn `end.char 0` | Not checked; trust backend | Check/flag | MVP simplicity; `segmentSection` is defensive |
| 7 | `request_id` | Mismatch only if request has one | Always require | Contract: echoed "when sent" |
| 8 | Version check order | Before schema | Rely on `const` | Clear error |
| 9 | Ajv errors | Shown raw (path + message) | Prettify | MVP |
| 10 | Rules 2-6, 9, 11, 12, id uniqueness | Trust schema / not checked | Re-check | Enforced by schema or unverifiable |

## Risks / Open Questions
- [RESOLVED: lexicographic pointer compare, strict start<end] Empty span invalid.
- [RESOLVED: flag only] One bad span never affects other claims.
- [RESOLVED: SP05 owns it; overlapping highlight segment uses a neutral highlight, no stripes] Shared-turn two-role painting.
- [RESOLVED: input is normalized English, no emoji; code-point slicing kept per contract] Surrogates, ZWJ, combining.
- [RESOLVED: Ajv errors shown raw] Message wording.
- [RESOLVED: export table above] Interface gaps (orderedClaims type, notProcessed surface, ClaimCheck key, orderEvidence arg, checks).
- [DEFERRED] Performance on very long transcripts.
- [DEFERRED] Whether `partial` + `section_not_processed` should gate claims in that section (SP04).
- [DEFERRED] Joining backend `span_out_of_range` warnings with our flag; ours is authoritative for rendering (SP03/04 banner copy).

## Acceptance Criteria
- `npm test` passes all R8 cases; `npm run typecheck` clean; `src/contract/` imports no React/DOM/fetch.
- Example pair: both validate; analysis has 5 claims, no flags, overall counts 1 each, `claimIdsFor(a,'contradicted','all')` = `['c-contradicted']`.
- Out-of-range claim span and evidence span each flag only the offending claim; other claims' `walkSpan` output is unchanged.
- `validateResponse` returns distinct `kind`s for version `"2.0.0"`, extra property, wrong `request_id`, duplicate claim ids.
- `buildChunks`: no turn index twice across chunks; touching ranges merge; +3 turns per click; clamped at 0 and `n-1`.
- `docs/contracts/` unchanged.
