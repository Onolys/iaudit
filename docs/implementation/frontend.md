# Frontend implementation

How `frontend/src/` works inside. Behaviour for users: [concepts](../concepts/review-ui.md). Overview: [architecture](../architecture.md#review-ui).

**Audience:** maintainers and coding agents.

Stack: Vite, React 19, strict TypeScript, Ajv (2020-12), Vitest. Schemas are imported from `docs/contracts/` through the `@contracts` alias, never copied.

## `contract/` (pure, no React)

| File | Key points |
|---|---|
| `validate.ts` | `validateRequest`, `validateResponse(raw, request)`. Adds the version, `request_id` and duplicate claim/evidence ID checks the schema cannot express. Returns `Result`, never throws. |
| `codepoints.ts` | `codePointLength`, `sliceCodePoints` via `Array.from`. All offsets are code points ([ADR 0002](../decisions/0002-offsets-count-code-points.md)). |
| `spans.ts` | `isSpanValid`: integers ≥ 0, start before end, in range, start char inside the item, claims in one item. `walkSpan` returns per-turn segments and throws on a bad span. `segmentSection` cuts a section into plain and claim pieces; an overlapping claim is skipped and stays plain. |
| `analysis.ts` | `analyzeResponse` builds per-claim checks (`claimSpanOk`, per-evidence ok, `spanOutOfRange`), verdict counts, and `orderedClaims` (valid claims by position, then invalid ones). Counts use the claim's section index. |
| `excerpts.ts` | `buildChunks` turns excerpt turn ranges plus expansion into display chunks. |

### Excerpt chunks

Each excerpt starts at its turn range. Expansion grows it by 3 turns per click (clamped to the transcript). Excerpts that overlap or touch (`start <= previous end + 1`) merge into one chunk. A chunk reports hidden turns above and below, counted up to its neighbour. The top and bottom excerpt of a chunk own its expand buttons.

## `transport/`

- `runAudit.ts`: `readRequestFile` (strips BOM, rejects empty/non-JSON/schema) and `auditRequest` (config check, POST or mock, reply checks, `analyzeResponse`). Exported `checkAuditResponse` shares post-parse response validation and load-error mapping with saved-item replay. Dependencies (`fetch`, config, mock registry) are injectable for tests.
- `client.ts`: `postAudit`. Two abort reasons, `timeout` and `cancelled`, are kept apart. Never throws.
- `errors.ts`: `LoadError` union and `isRetryable`.
- `ErrorScreen.tsx`: maps each error to a title and buttons. `onChooseFile` is optional; saved-item errors omit that action. Which errors offer Retry: see the [error table](../reference/review-ui.md#error-screens).
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
`Header` accepts optional `inputRef` and `onFile`; the file input and upload button
render only when `onFile` is supplied. eaudit supplies both; saved replay omits them.

`LeftPane` renders section cards, per-section "Unplaced claims" and a final "Claims outside the supplied assessment" card.

## `claim-detail/`

`ClaimDetail` remounts per claim, so the active concern and expansion reset. `orderEvidence` splits evidence into placed and unplaceable; `firstPerId` (in `ClaimDetail.tsx`) keeps only the first of duplicate evidence ids. `partsForTurn` cuts a turn at every highlight edge: one excerpt = highlight, several = overlap, uncovered text in an excerpt row = dim. A concern is clickable only if it cites at least one placed excerpt. `out_of_scope` claims show the reason instead of concerns and excerpts.

## Edge rules

- Empty turn shows "(empty turn)".
- Missing timestamp shows `#<turn index>`.
- Unknown concern types fall back to the raw value.
- A claim whose section index is outside the assessment goes to the "outside" card.


## `eval/`

`EvalApp` owns a small view union for list, run, item and compare; there is no router.
An item carries its origin and comparison pair so Back restores the correct screen.
Switching views unmounts departing requests/pollers. Returning to the list rescans
server state rather than reusing a stale resume attachment.

`evalApi.ts` injects fetch, encodes identifiers, omits credentials and returns typed
`Result` errors. Ajv validates responses against the in-place eval API schema via
`@eval-api`; it also resolves embedded B3 report schemas. Metrics-only 404
`not_found` becomes successful null. Read/POST timeouts are 10/30 seconds and bound
body reads as well as fetch. API errors retain their server status/message/detail.

`useRunLifecycle` drives RunPanel start/download/abort/resume attachment;
`usePolling` performs sequential polls with cancellation/generation protection.
RunsList shares active progress instead of starting another poller. RunDetail polls
pending/running scoring, refetches metrics on terminal scoring and disables Re-score
while scoring or the audit run is active. Three consecutive polling misses show the
lost-contact banner while retaining the last run data.

`toMetricRows` is the only renderer-side reader of the raw B3 metrics-report shape.
It groups level/slice/metric in first-seen order, pairs policies and preserves paper
reference evaluator labels/notes. Item failure counts come from `report.items`;
policy-none rates retain their level/slice as supplemental values. MetricsTable and
RunInfoBlock are pure props. Persisted model/prompt provenance comes from
`run_info.fingerprint`, not top-level model fields.

`buildLoadResult(request: unknown, response: unknown)` is synchronous and pure:
validateRequest, shared checkAuditResponse, then analyzeResponse; source is `service`.
It does not parse JSON or fetch. ItemDetail uses it to supply unchanged ReviewShell
with a run/item key, resetting review selection per saved item. FailedItem bypasses
review and renders saved failure metadata. Unmapped detail names the mapping
limitation and replays a saved valid response if present. Stale/invalid saved data
uses existing ErrorScreen without upload/file-choice actions.

`gold/GoldPanel` dispatches by gold kind; guarded native TofuEval gold renders as a
collapsible sentence list, while unknown/malformed shapes use JSON fallback. It
never imports review implementation files. CompareView reads saved comparisons,
shows neutral signed deltas and opens items in either run. Both HTTP 409 and the
actual cross-dataset HTTP 422 remain inline API errors.

ItemList, ItemDetail and CompareView abort old requests and ignore stale callbacks
on identity changes/unmount. Styling is isolated in their component stylesheets and
metrics/gold stylesheets. The review shell, panes, reducer and ClaimDetail remain
unchanged. The current response schema pins `0.0.1`; non-conforming saved bodies
show a validation error, and the owner deletes those files.

See [Eval UI reference](../reference/eval-ui.md) and
[frontend tests](../testing/frontend.md) for behavior and verification.
