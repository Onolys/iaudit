---
status: draft
summary: Three tasks: review state reducer and shared counts, app shell with header, then left pane with claim rendering and right-pane container.
date: 2026-10-10
---
# Tasks: 04 Review shell and left pane

Source of truth: docs/agent_files/feat-review-ui-20261010-2330/04-review-shell-left-pane/PRD.md. Builds the app screen, selection/navigation state, header and the left pane. Depends on 01, 02, 03 (02 for analysis helpers, 03 for loader and state views) and composes 05's `ClaimDetail`; declare the dependency, no placeholder is specified.

| # | Task | Depends on | Status |
|---|---|---|---|
| 1 | Review state reducer and VerdictCounts | none | todo |
| 2 | App screen and header | 1 | todo |
| 3 | Left pane, claim text and right-pane container | 1, 2, 05 | todo |

## Task 1 — Review state reducer and VerdictCounts
What it is / what it means: The pure navigation core and the count buttons that drive it (PRD R3, R4; Decisions 1-3, 9).
What changes at a high level: Add `reviewState.ts` with the `Nav`/`ReviewState` types and reducer actions init, `selectClaim`, `navigate`, `step`, using 02's `claimIdsFor`. Initial selection is the first claim in document order. Add `VerdictCounts` (five buttons in verdict order using 01's `VERDICT_STYLE`, icon + label + number, zero disabled, `aria-pressed` when matching active nav, scope `'all'` or a section index). Reducer tests per the PRD.
Done when: tests show click inside the active list keeps nav and moves position, outside clears nav, step clamps, navigate to empty is a no-op; zero counts are disabled.

## Task 2 — App screen and header
What it is / what it means: The top-level screen driven by the 03 loader (PRD R1, R2, R7; Decisions 8, 11).
What changes at a high level: Wire `App` to `useAuditLoader`: idle prompt text, `LoadingView`, `ErrorScreen`, and on ok `WarningsBanner` plus `ReviewShell` keyed by a `loadId` counter bumped on each entry into ok. Build `Header` with the hidden file input (reset value after pick, enabled while loading, calls `loadFile`), file name, `request_id` or "No request ID", "Mock data" chip, and `VerdictCounts` at scope `'all'`. Wrap to two rows below ~1100 px; app `min-width` 960 px.
Done when: example mock load shows five counts of 1 and `example-001`; re-uploading the same file re-fires and resets the review; no stale audit during loading or error.

## Task 3 — Left pane, claim text and right-pane container
What it is / what it means: The reading surface and the right-pane host (PRD R5, R6; Decisions 4-7, 10, 12).
What changes at a high level: Add `ReviewShell` (`useReducer`, 55/45 grid, only the left pane scrolls), `LeftPane`, `SectionCard` (sticky header with label fallback, neutral "Score <value>" chip with tooltip, "Not processed" badge, ⋯ popover with `VerdictCounts` at section scope, no `overflow: hidden`), and `ClaimText` using 02's `segmentSection` with `span[role=button]` claims, verdict-styled underlines, `title`, selected background. Add the "Unplaced claims" chip strip and trailing "outside" card; nav/step calls `scrollIntoView({block:'nearest'})`. Add `RightPane` with `NavStepper` and 05's `ClaimDetail` (`key`, `check` passed), plus the "No claim selected." and no-claims states.
Done when: section `textContent` equals the supplied text; underline colour/style per verdict; bad-span claim shows as a selectable chip and passes `claimSpanOk === false`; not-processed section shows badge with disabled counts; stepper shows `‹ n of N ›` only while nav is active; no fetch or Ajv imports in panes.

## Manual steps (human)
Eyeball in desktop Chrome: sticky headers on a long fixture, underline wrapping, header at 960 / 1100 / 1440 px.
