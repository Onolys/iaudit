---
status: draft
summary: App shell, review state and navigation, header with verdict stats, and the left pane (section cards, exact-text claim rendering with verdict underlines, count-driven navigation, unplaceable-claim handling).
date: 2026-10-10
---
# PRD: 04 Review shell and left pane

Repo/branch: iaudit / `feat/review-ui` · Depends on: 01-frontend-scaffold, 02-contract-core, 03-transport-mock-errors · Owns: `frontend/src/app/` (`App.tsx` wiring, `reviewState.ts`, `Header`, `UploadControl`, `VerdictCounts`, `LeftPane`, `SectionCard`, `SectionMenu`, `ClaimText`, `RightPane` container, `NavStepper`, layout CSS, tests)

## TL;DR
The screen the reviewer lives in: header (upload, `request_id`, overall verdict counts), one scrolling left pane of sticky-headed section cards with the assessment text exactly as written and every claim underlined by verdict, and a right-pane container (NavStepper + SP05's `ClaimDetail`). Verdict counts are navigation. Owns selection and nav state.

## Problem
The left pane is where the reviewer sees the audit in context. Failure modes: text altered by rendering (collapsed whitespace, shifted highlights after an emoji), colour as the only signal, a claim with a bad span silently vanishing, nav state going stale after direct clicks, and sticky headers breaking inside nested scroll areas.

## Goals / Non-Goals
**Goals**
- Section text visible exactly as supplied; claims placed by code-point spans from SP02, flat underlines.
- Header counts and per-section ⋯ counts navigate; ‹ n of N › steps.
- Defined behaviour for every odd case: direct click during nav, zero counts, unplaceable claims, unprocessed sections, empty audit, new upload.

**Non-Goals**
- Claim detail contents, excerpts, expansion (SP05). Loading/error/banner components (SP03). Span math, counts, ordering (SP02).
- Resizable panes, filters, expand-all, accept/dismiss, export, score interpretation, mobile, app keyboard shortcuts.

## Requirements
**R1 Screen composition** (`App`): header always visible; main area switches on SP03 `LoaderState`: `idle` -> empty prompt "Upload a request JSON file to begin."; `loading` -> `LoadingView`; `error` -> `ErrorScreen`; `ok` -> `WarningsBanner` (full width, above the panes, outside both scrolls) + `<ReviewShell key={loadId}/>`. A `source: 'mock'` result shows a "Mock data" chip in the header so a fixture is never mistaken for a real audit.

**R2 Header** (outside both scroll areas): `UploadControl` (button + hidden `<input type=file accept=".json,application/json">`; shows file name; resets input value so re-picking the same file fires; stays enabled while loading, re-upload cancels in-flight work per SP03), `request_id` (or "No request ID"), then one row of five count buttons in verdict order: icon + label + number, e.g. `✓ Supported 3`. At <= ~1100 px the header wraps to two rows (upload + id above, counts below); app `min-width` 960 px. Counts are SP02 `analysis.counts.overall`.

**R3 State** (`reviewState.ts`, pure reducer + `useReducer` in `ReviewShell`):
```ts
type Nav = { verdict: Verdict; scope: 'all' | number; claimIds: string[]; position: number };
type ReviewState = { selectedClaimId: string | null; nav: Nav | null };
// request/response/analysis come from LoadResult (immutable); not duplicated in the reducer
```
Actions and effects:
| Action | Effect |
|---|---|
| init | `selectedClaimId` = `analysis.orderedClaims[0]?.id ?? null` (document order; unplaceable claims sort last, so a placed claim wins); `nav = null` |
| `selectClaim(id)` (click on claim or chip) | if `nav` active and `id` in `nav.claimIds`: keep nav, `position = index`; else `nav = null`. Selection set either way |
| `navigate(verdict, scope)` (count click) | `claimIds = claimIdsFor(analysis, verdict, scope)`; if empty: no-op; else `nav = {verdict, scope, claimIds, position: 0}`, select `claimIds[0]` (re-clicking the active count restarts at 1) |
| `step(±1)` | `position` clamped to `[0, N-1]`; select that id. No wrap; ‹ disabled at 1, › at N |

**R4 Counts as controls** (`VerdictCounts`, shared by header and ⋯ menu): a count of 0 renders as a disabled button (`aria-disabled`, muted, still shows icon + label + `0`, no action). The count matching the active `nav` (same verdict and scope) is `aria-pressed`. Per-section counts: `analysis.counts.bySection[i]`.

**R5 Left pane layout**: the left pane is the **single scroll container** (`overflow-y: auto`, `min-height: 0` inside a flex/grid chain from a `100vh` app). Each section is a card with a sticky header (`position: sticky; top: 0`) containing: label (fallback "Section N", N = index+1, only when `label` absent), score chip, "Not processed" badge, ⋯ button. No ancestor between a sticky header and the pane may set `overflow` other than `visible` (cards round corners on their own header/border, not via `overflow: hidden`), else sticky silently fails. A header stays inside its card, so the next card's header replaces it on scroll. The ⋯ popover is absolutely positioned inside the header with higher z-index, closes on outside click, Esc, or after picking a count, and is a native `<button>` (focusable) so it is usable without app shortcuts.
- Score chip: neutral outline, text `Score <value>` (`String(score)` as supplied, number or string), `title="Display only, not an audit result"`; omitted when `score` absent. Never colour-coded.
- "Not processed" badge: sections in SP02 `notProcessedSections`. Text still shown (muted), its ⋯ counts are all disabled. Claims returned for such a section are rendered normally (D6).
- Right pane: `RightPane` = sticky-free container with its own scroll: `NavStepper` row, then `<ClaimDetail key={claim.id} claim request spanOutOfRange />` (key resets SP05's expansion state per claim). No selection -> "No claim selected."; empty audit (`claims: []`) -> left text plain, right pane "This audit contains no claims."

**R6 Claim rendering** (`ClaimText`): `segmentSection(request, i, analysis.checks)` yields ordered `plain` and `claim` pieces whose `text` was produced by code-point slicing. Render the section in one block with `white-space: pre-wrap; overflow-wrap: anywhere` and pieces as adjacent children with no JSX-inserted whitespace, so `textContent` equals `section.text` exactly (newlines, runs of spaces, emoji preserved). Claim piece = `<span role="button" tabindex="0">` (not `<button>`: inline buttons do not wrap across lines) activating on click, Enter, Space (basic accessibility, not an app shortcut):
- Underline via `text-decoration` (colour, style from SP01 `VERDICT_STYLE`, thickness 2.5 px, offset 3 px; hover 4 px + `cursor: pointer`). Style: solid / dashed (insufficient) / dotted (out of scope).
- Colour is never the only cue: `data-suffix` (verdict icon, plus ` ⚠` if flagged) painted with CSS `::after { content: attr(data-suffix) }` as a small superscript, so DOM text is unchanged; `title` = verdict label; `data-claim-id` for scroll lookup.
- Selected: neutral background (`selectedClaimBackground`), `box-decoration-break: clone`.
- **Evidence-only flag** (claim's own span valid, an evidence span bad): underlined normally with ` ⚠`; `spanOutOfRange` passed to SP05.
- **Unplaceable claim** (own span invalid, bad section index, or overlap-flagged): never underlined, never shifts anything. Shown as a chip in an "Unplaced claims" strip at the bottom of its section card (claim section index invalid -> one trailing card "Claims outside the supplied assessment"): `icon + verdict label + id`, warning "position doesn't fit the supplied text", no text excerpt (nothing may be displayed that was not sliced from input). Chips are selectable like claims and take the same selected style.
- Scroll-into-view: nav/step selections call `scrollIntoView({block: 'nearest'})` on `[data-claim-id]` (CSS `scroll-margin-top` = sticky header height); direct clicks do not scroll.

**R7 New upload**: `ReviewShell` is keyed by load; any new `loadFile` unmounts it, so selection, nav, open menus, and scroll position all reset. Failed loads leave no stale audit (D8).

## Architecture
```
useAuditLoader (SP03) -> App
  header: UploadControl, request_id, Mock chip, VerdictCounts(scope 'all')
  ok -> WarningsBanner (SP03) + ReviewShell(result)
          useReducer(reviewState)  ->  LeftPane -> SectionCard* -> ClaimText, SectionMenu(VerdictCounts)
                                       RightPane -> NavStepper + ClaimDetail (SP05)
```
Assumed from SP02 (confirm when SP02 tasks exist): `ResponseAnalysis { orderedClaims: Claim[]; checks: Record<claimId, ClaimCheck>; counts; ... }` (ClaimCheck has `spanOutOfRange`), `claimIdsFor`, `segmentSection(request, sectionIndex, checks)`, `notProcessedSections`. Assumed from SP05: `ClaimDetail({claim, request, spanOutOfRange})`, owns excerpt-expansion state internally. Tokens from SP01: `VERDICT_STYLE`, `selectedClaimBackground`. Components memoised per claim/section so a selection change repaints two claims, not the document.

## Decisions
| # | Decision | Choice | Alternatives considered | Why |
|---|---|---|---|---|
| 1 | Direct click during nav | Keep nav if claim is in the list (move position), else clear nav | Always clear; always keep | Stepping stays coherent; no stepper for a claim outside its list |
| 2 | Stepping at ends | Clamp, disable button | Wrap | Position "n of N" stays truthful; no surprise jump |
| 3 | Zero count | Disabled, still visible | Hidden | Shows "none found" without implying unchecked |
| 4 | Claim element | `span[role=button]` | `<button>`; `<a>` | Inline buttons do not wrap; keeps text node flow |
| 5 | Verdict icon in text | CSS `::after` from data attribute | Real DOM icon | Keeps `textContent` identical to input; satisfies colour+icon |
| 6 | Claims in a not-processed section | Render them | Hide/gate | Hiding returned data is worse than an inconsistent-looking badge; banner explains |
| 7 | Unplaceable claims | Chip strip in card, no text | Clamp the span to bounds; drop | Clamping invents a quote location; dropping hides a verdict |
| 8 | New upload | Replace whole view immediately, discard old audit | Keep old audit until new succeeds | Header/pane never mismatch; one case at a time; simple |
| 9 | Initial selection | First in document order | First in response order | Reviewer reads top-down; response order is arbitrary |
| 10 | Scroll container | Left pane is the only scroll; header outside | Page scroll with sticky | Sticky works only against a known scroller; panes scroll independently |
| 11 | Pane widths | Equal, `minmax(420px, 1fr)` each | Fixed 60/40; resizable | Adjust by eye in SP06 |
| 12 | Narrow header | Wrap to two rows, min app width 960 px | Overflow menu; truncate | Counts must stay visible; desktop-only |
| 13 | Score label | `Score <value>` + tooltip | Bare number | Prevents reading it as an audit result |

## Manual steps
- Human check in a real desktop browser (Chrome + Firefox): sticky headers over a long fixture, underline wrapping across lines, header at 960 / 1100 / 1440 px. jsdom cannot verify layout.

## Risks / Open Questions
- [OPEN] Narrow-desktop header layout: wrap-to-two-rows at ~1100 px with a 960 px floor is a provisional default; user to confirm (brainstorm left it open).
- [OPEN] Verdict superscript icons on every claim may add noise on long assessments (brainstorm risk); judge on SP06's long fixture, fallback is icon only on hover/selection plus `title`.
- [OPEN] Pane width ratio and exact underline thickness (SP06 visual pass).
- [OPEN] SP02 shapes assumed above (`orderedClaims` element type, `checks` keyed by id, unplaced detection = absent from `segmentSection` pieces); verify at SP02 tasks time.
- [RESOLVED: D1] Nav vs direct click. [RESOLVED: D7] Out-of-range claim display. [RESOLVED: D8] State on new upload.
- [RESOLVED: pre-wrap] Newlines/whitespace preserved without altering text; combining marks or ZWJ sequences cut mid-grapheme by a span follow the contract's code-point rule.
- [DEFERRED] Tab-order burden with many claims (one stop each); revisit only if reviewers complain, shortcuts stay out of scope.

## Acceptance Criteria
- Example mock load: header shows `✓ Supported 1 · ◐ Partial 1 · ✕ Contradicted 1 · ? Insufficient 1 · ▨ Out of scope 1` with `example-001`; first claim (by document order) is selected with neutral background; no stepper visible.
- Section body `textContent` equals `assessment[i].text` exactly, including a fixture with newlines, double spaces, and an emoji before a later claim (that claim's underline covers the right words).
- Every underline has verdict colour + icon + `title`; insufficient is dashed, out-of-scope dotted.
- Clicking `✕ Contradicted` (header) selects the first contradicted claim and shows `‹ 1 of N ›`; with N = 1 both arrows disabled. ⋯ menu counts act on that section scope; picking one closes the menu.
- Zero count is disabled and a click changes nothing.
- Reducer tests: direct click on a claim inside the active list updates position and keeps nav; outside it clears nav; step clamps; navigate to an empty list is a no-op.
- Claim with out-of-range span: not underlined, no other highlight moves (compare `textContent` and underline ranges to the unflagged case); appears as a selectable chip with warning; selecting it passes `spanOutOfRange: true` to `ClaimDetail`.
- Section in `section_not_processed`: "Not processed" badge, all its counts disabled.
- Score chip renders `Score 2` neutral for the example; absent when `score` missing.
- Re-upload (including the same file) unmounts the review: selection/nav reset, no old audit visible during loading or after an error.
- Manual: sticky header visibly pins per card and is replaced by the next card's header in a scrolled long fixture; header wraps cleanly at 1000 px.
- `ReviewShell`/panes import no fetch or Ajv; `docs/contracts/` unchanged.
