---
status: draft
summary: App shell, review state and navigation, header with verdict stats, and the left pane (section cards, verdict-underlined claims, count-driven navigation, unplaced-claim chips). MVP-trimmed.
date: 2026-10-10
---
# PRD: 04 Review shell and left pane

Repo/branch: iaudit / `feat/review-ui` · Depends on: 01-frontend-scaffold, 02-contract-core, 03-transport-mock-errors · Owns: `frontend/src/app/` (`App.tsx` wiring, `reviewState.ts`, `Header`, `VerdictCounts`, `LeftPane`, `SectionCard`, `ClaimText`, `RightPane`, `NavStepper`, layout CSS, tests)

## TL;DR
Header (upload, `request_id`, overall verdict counts), one scrolling left pane of section cards with sticky headers and every claim underlined by verdict, and a right pane (`NavStepper` + SP05 `ClaimDetail`). Verdict counts are navigation. Owns selection and nav state. Hackathon MVP: simplest thing that works.

## Problem
The reviewer needs the audit in context: assessment text as written, each claim visibly tied to its verdict, fast jumping between claims of one verdict, and no claim silently vanishing when its span is bad.

## Goals / Non-Goals
**Goals**
- Section text shown exactly as supplied; claims placed via SP02 `segmentSection`.
- Header and per-section counts navigate; `‹ n of N ›` steps.
- Bad-span claims stay selectable (chip + warning).

**Non-Goals**
- Claim detail (SP05), loading/error/banner components (SP03), span math/counts/ordering (SP02).
- Resizable panes, filters, accept/dismiss, export, mobile, keyboard shortcuts, per-claim inline icons, memoisation tuning, emoji/unicode handling (input is normalized English).

## Requirements
**R1 Screen** (`App`): header always visible. Main area switches on SP03 `LoaderState.status`: `idle` -> "Upload a request JSON file to begin."; `loading` -> `LoadingView`; `error` -> `ErrorScreen`; `ok` -> `WarningsBanner` above the panes + `<ReviewShell result={state.result} key={loadId}/>` (`loadId` = App-local counter bumped on each entry into `ok`). `result.source === 'mock'` shows a "Mock data" chip in the header.

**R2 Header**: file button (hidden `<input type=file accept=".json,application/json">`; reset `value` after pick so the same file re-fires; calls SP03 `loadFile`; stays enabled while loading), file name, `request_id` (or "No request ID"), then five count buttons in verdict order using SP01 `VERDICT_STYLE`: icon + label + number (from `analysis.counts.overall`). Wraps to two rows (upload + id above, counts below) below ~1100 px; app `min-width` 960 px.

**R3 State** (`reviewState.ts`, pure reducer, `useReducer` in `ReviewShell`):
```ts
type Nav = { verdict: Verdict; scope: 'all' | number; claimIds: string[]; position: number };
type ReviewState = { selectedClaimId: string | null; nav: Nav | null };
```
| Action | Effect |
|---|---|
| init | `selectedClaimId = analysis.orderedClaims[0]?.id ?? null`; `nav = null` |
| `selectClaim(id)` | if `nav` and `id` in `nav.claimIds`: `position = index`; else `nav = null`. Select `id` |
| `navigate(verdict, scope)` | `claimIds = claimIdsFor(analysis, verdict, scope)`; empty -> no-op; else `nav = {…, position: 0}`, select `claimIds[0]` |
| `step(±1)` | clamp `position` to `[0, N-1]`; select that id. No wrap; arrow disabled at ends |

**R4 Count buttons** (`VerdictCounts`, used by header with scope `'all'` and by each section's ⋯ menu with scope = section index): count 0 -> disabled. Button matching active `nav` (verdict + scope) is `aria-pressed`. Section counts from `analysis.counts.bySection[i]`.

**R5 Left pane**: the only scroll container for the text (`overflow-y: auto; min-height: 0` in a flex/grid chain from a `100vh` app). Fixed layout: left 55% / right 45% (`grid-template-columns: 55fr 45fr`), right pane scrolls independently. Each section is a card with a sticky header (`position: sticky; top: 0`): label (fallback "Section N"), neutral score chip, "Not processed" badge, ⋯ button. Cards must not use `overflow: hidden` (breaks sticky). ⋯ opens a simple absolutely-positioned popover with `VerdictCounts`; closes on outside click or after a pick.
- Score chip: neutral outline, `Score <value>` (as supplied), `title="Display only, not an audit result"`; omitted if `score` absent. Never colour-coded.
- "Not processed": sections in SP02 `notProcessedSections(response)` (a `Set<number>`) get the badge and muted text; their ⋯ counts are disabled; claims returned for them still render normally.
- Right pane: `NavStepper` (`‹ n of N ›`, only while `nav` is active), then `<ClaimDetail key={claim.id} claim={claim} request={request} check={analysis.checks[claim.id]} />` (SP05 R1 signature; `claim` looked up in `analysis.orderedClaims`). No selection -> "No claim selected."; no claims at all -> left text plain, right "This audit contains no claims."

**R6 Claim rendering** (`ClaimText`): `segmentSection(request, i, analysis.checks, analysis.orderedClaims)` returns `Piece[]` (`plain` | `claim`, with `text`, `claimId`). Render in one block, `white-space: pre-wrap; overflow-wrap: anywhere`, pieces as adjacent children (no inserted whitespace) so `textContent` equals `section.text`. Claim piece = `<span role="button" tabindex="0" data-claim-id title={verdict label}>` (span, not `<button>`, so it wraps across lines); activates on click, Enter, Space.
- Underline via `text-decoration`: colour and style from `VERDICT_STYLE` (solid / dashed insufficient / dotted out of scope), 2px thick, 3px offset; hover 3px + pointer. Verdict is also carried by the header count icons and SP05's verdict badge; no per-claim inline icons.
- Selected claim: neutral `selectedClaimBackground`, `box-decoration-break: clone`.
- **Unplaced claim** (`!check.claimSpanOk`, or claim section index outside the request): never underlined; shown as a chip in an "Unplaced claims" strip at the bottom of its card (invalid section index -> one trailing card "Claims outside the supplied assessment"): verdict icon + label + id + warning "position doesn't fit the supplied text". No text excerpt. Selectable, same selected style.
- Claim with valid span but a bad evidence span (`check.spanOutOfRange && check.claimSpanOk`): underlined normally; SP05 shows the warning via `check`.
- Nav/step selection calls `scrollIntoView({block:'nearest'})` on the `[data-claim-id]` element (`scroll-margin-top` = sticky header height); direct clicks do not scroll.

**R7 New upload**: `ReviewShell` is keyed by `loadId`; a new load unmounts it, resetting selection, nav, menus, scroll. Loading/error states show no stale audit.

## Architecture
```
useAuditLoader (SP03) -> App
  Header: file input, request_id, Mock chip, VerdictCounts(scope 'all')
  ok -> WarningsBanner + ReviewShell(result: {request, response, analysis, source})
          useReducer(reviewState) -> LeftPane -> SectionCard* -> ClaimText, VerdictCounts (⋯)
                                     RightPane -> NavStepper + ClaimDetail (SP05)
```
Consumed from SP02 (verified against its export table): `analysis: ResponseAnalysis {orderedClaims, checks: Record<claimId, ClaimCheck>, counts {overall, bySection}}`, `ClaimCheck {spanOutOfRange, claimSpanOk, evidence}`, `claimIdsFor`, `notProcessedSections`, `segmentSection(request, i, checks, claims)`. From SP03: `useAuditLoader`, `LoaderState`, `LoadResult {ok, request, response, analysis, source}`, `LoadingView`, `ErrorScreen`, `WarningsBanner`. From SP01: `VERDICT_STYLE`, `selectedClaimBackground`.

## Decisions
| # | Decision | Choice | Why |
|---|---|---|---|
| 1 | Direct click during nav | Keep nav if claim in list, else clear | Stepper stays coherent |
| 2 | Stepping at ends | Clamp, disable | Truthful "n of N" |
| 3 | Zero count | Disabled, visible | Shows "none found" |
| 4 | Claim element | `span[role=button]` | Wraps across lines |
| 5 | Per-claim icons | None; underline colour/style + title + header and right-pane badges | Less noise, simplest; text stays unaltered |
| 6 | Claims in not-processed section | Render them | Don't hide returned data |
| 7 | Unplaceable claims | Chip strip, no text | Never invent a quote location |
| 8 | New upload | Unmount whole review | Simple, no mismatch |
| 9 | Initial selection | First in document order | Reviewer reads top-down |
| 10 | Layout | Left pane scrolls, header fixed, 55/45, 2px underline (3px hover) | Fixed values; sticky needs known scroller |
| 11 | Narrow header | Wrap below ~1100 px, min width 960 px | Counts stay visible |
| 12 | Score label | `Score <value>` + tooltip | Not read as audit result |

## Manual steps
- Eyeball in desktop Chrome: sticky headers on a long fixture, underline wrapping, header at 960 / 1100 / 1440 px.

## Risks / Open Questions
- [RESOLVED: wrap to two rows below ~1100 px; min width 960 px] O-04-1 Narrow header.
- [RESOLVED: no per-claim inline icons (D5)] O-04-2 Superscript noise.
- [RESOLVED: 55/45, 2px underline, 3px hover (D10)] O-04-3 Widths and thickness.
- [RESOLVED: aligned to SP02 export table and SP03 `LoadResult`; unplaced = `!claimSpanOk`] O-04-4 Assumed shapes.
- [RESOLVED: input is normalized English, no emoji; colour palette fixed in SP01] Unicode and colour-blindness checks dropped.
- [DEFERRED] Tab-order burden with many claims; keyboard shortcuts; memoisation if long fixtures lag.

## Acceptance Criteria
- Example mock load: header shows five counts of 1 with `example-001`; first claim in document order is selected (neutral background); no stepper.
- Section body `textContent` equals `assessment[i].text`.
- Each underline has verdict colour, `title`; insufficient dashed, out-of-scope dotted.
- Clicking a header verdict count selects its first claim and shows `‹ 1 of N ›`; ⋯ counts use section scope and close the menu on pick. Zero count is disabled.
- Reducer tests: click inside active list keeps nav and moves position; outside clears nav; step clamps; navigate to empty is a no-op.
- Claim with bad span: no underline, appears as selectable chip with warning; selecting it passes `check.claimSpanOk === false` to `ClaimDetail`.
- `section_not_processed` section: badge, counts disabled. Score chip shows `Score 2` for the example, absent if `score` missing.
- Re-upload (same file too) resets selection and nav; no old audit during loading or after an error.
- Panes import no fetch or Ajv; `docs/contracts/` unchanged.
