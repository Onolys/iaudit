# Frontend implementation

How `frontend/src/` works inside. Behaviour for users: [concepts](../concepts/review-ui.md). Overview: [architecture](../architecture.md#review-ui).

**Audience:** maintainers and coding agents.

Stack: Vite, React 19, strict TypeScript, Ajv (2020-12), Vitest. Schemas are imported from `docs/contracts/` through the `@contracts` alias, never copied.

## `contract/` (pure, no React)

| File | Key points |
|---|---|
| `validate.ts` | `validateRequest`, `validateResponse(raw, request)`. Adds the version, `request_id` and duplicate-claim-id checks the schema cannot express. Returns `Result`, never throws. |
| `codepoints.ts` | `codePointLength`, `sliceCodePoints` via `Array.from`. All offsets are code points ([ADR 0002](../decisions/0002-offsets-count-code-points.md)). |
| `spans.ts` | `isSpanValid`: integers ≥ 0, start before end, in range, start char inside the item, claims in one item. `walkSpan` returns per-turn segments and throws on a bad span. `segmentSection` cuts a section into plain and claim pieces; an overlapping claim is skipped and stays plain. |
| `analysis.ts` | `analyzeResponse` builds per-claim checks (`claimSpanOk`, per-evidence ok, `spanOutOfRange`), verdict counts, and `orderedClaims` (valid claims by position, then invalid ones). Counts use the claim's section index. |
| `excerpts.ts` | `buildChunks` turns excerpt turn ranges plus expansion into display chunks. |

### Excerpt chunks

Each excerpt starts at its turn range. Expansion grows it by 3 turns per click (clamped to the transcript). Excerpts that overlap or touch (`start <= previous end + 1`) merge into one chunk. A chunk reports hidden turns above and below, counted up to its neighbour. The top and bottom excerpt of a chunk own its expand buttons.

## `transport/`

- `runAudit.ts`: `readRequestFile` (strips BOM, rejects empty/non-JSON/schema) and `auditRequest` (config check, POST or mock, reply checks, `analyzeResponse`). Dependencies (`fetch`, config, mock registry) are injectable for tests.
- `client.ts`: `postAudit`. Two abort reasons, `timeout` and `cancelled`, are kept apart. Never throws.
- `errors.ts`: `LoadError` union and `isRetryable` (network, timeout, cancelled, 5xx, 408, 429).
- `ErrorScreen.tsx`: maps each error to a title and buttons. Retry-only kinds: network, timeout, cancelled, 5xx.
- `mock/registry.ts`: builds pairs from `import.meta.glob` (lazy, so real-service sessions never fetch them). Lookup matches on `request_id`.
- `useAuditLoader.ts`: state machine `idle → loading → ok | error`.
  - Each attempt gets a generation number and an `AbortController`. A new upload, retry or reset aborts the old one; late replies from old generations are dropped.
  - Cancel aborts the controller. Cancel wins even if the result arrived first.
  - Retry reuses the last valid request and only runs for retryable errors.

## `app/`

`App.tsx` owns the loader and the file input. `ReviewShell` is remounted per load (`key`), so selection never leaks between audits. `reviewState.ts` is a reducer with three actions:

- `selectClaim`: select; keeps the navigation list if the claim is in it, else drops it.
- `navigate(verdict, scope)`: build the claim list for that verdict (all, or one section) and select the first. No claims = no change.
- `step(±1)`: move within the list, clamped.

The shell scrolls the left pane only after navigation or stepping, not after a direct click.

`LeftPane` renders section cards, per-section "Unplaced claims" and a final "Claims outside the supplied assessment" card.

## `claim-detail/`

`ClaimDetail` remounts per claim, so the active concern and expansion reset. `orderEvidence` splits evidence into placed and unplaceable; duplicate evidence ids keep only the first. `partsForTurn` cuts a turn at every highlight edge: one excerpt = highlight, several = overlap, uncovered text in an excerpt row = dim. A concern is clickable only if it cites at least one placed excerpt. `out_of_scope` claims show the reason instead of concerns and excerpts.

## Edge rules

- Empty turn shows "(empty turn)".
- Missing timestamp shows `#<turn index>`.
- Unknown concern types fall back to the raw value.
- A claim whose section index is outside the assessment goes to the "outside" card.
