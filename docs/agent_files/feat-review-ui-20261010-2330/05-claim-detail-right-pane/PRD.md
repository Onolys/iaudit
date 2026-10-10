---
status: draft
summary: React ClaimDetail component (right pane body) - verdict, explanation, suggestion box, clickable concerns, transcript-order excerpts with role styling and GitHub-style context expansion, plus empty and out-of-range states.
date: 2026-10-10
---
# PRD: 05 Claim detail (right pane)

Repo/branch: iaudit / `feat/review-ui` · Depends on: 01-frontend-scaffold, 02-contract-core (composed by 04-review-shell-left-pane) · Owns: `frontend/src/claim-detail/` (components, `concernLabels.ts`, CSS, colocated tests)

## TL;DR
One component, `ClaimDetail`, that renders everything about the selected claim below the NavStepper: verdict badge, explanation, "Suggestion - not applied" box, concerns (click to emphasise cited excerpts), and transcript-order excerpts with per-excerpt role styling and +3-turn up/down expansion. It owns only local UI state (concern emphasis, expansion counts) and does all position work through SP02.

## Problem
This pane is where a reviewer decides whether a potential concern is valid. It must show exactly the uploaded words (sliced, never invented), keep roles and verdicts legible without colour alone, handle overlapping or invalid positions without breaking, and never imply that the suggestion was applied or that "no excerpt" means "wrong".

## Goals / Non-Goals
**Goals**
- Render requirement order: badge, explanation, suggestion, concerns, excerpts.
- Excerpts in transcript order; cross-turn span = one excerpt; exact span highlighted, rest of span's turns dimmed.
- Expansion by GitHub-diff model using `buildChunks`; no turn ever shown twice.
- Graceful states: no evidence, out_of_scope, flagged span, dangling concern refs, shared turn between roles.

**Non-Goals**
- NavStepper, left pane, app state, selection (SP04). Transport/errors (SP03).
- Accept/dismiss/comment, copying or applying suggestions, export, concern filter, expand-all, full-transcript mode, keyboard shortcuts.
- Span math (SP02). Final colours (SP06; consume SP01 tokens only).
- Any contract change.

## Requirements

**R1 Interface.**
```ts
ClaimDetail({ claim: Claim, request: AuditRequest, check: ClaimCheck }) // check from SP02 analysis.checks[claim.id]
```
`check.spanOutOfRange` is the flag named in the SP02/SP04 interface; the full `ClaimCheck` is passed because `orderEvidence(request, claim, checks)` needs per-evidence results. [RESOLVED: SP04 PRD updated to pass `check`.] `ClaimDetail` wraps its body in `key={claim.id}` so all local state resets when selection changes (D1).

**R2 Header block.** Verdict badge from `VERDICT_STYLE` (icon + label + colour, all three). Explanation as plain text. For `insufficient_evidence`, a fixed line under the explanation: "Not substantiated by the supplied interview. This is not the same as contradicted." If `check.spanOutOfRange`, a warning strip at top: "A position returned for this claim does not fit the supplied input. Affected text is withheld; other content is unchanged."

**R3 Suggestion.** Only when `suggested_revision` is a non-null string: a bordered box with heading "Suggestion - not applied" (use the em dash as in the mission wording) and the text. No button, no copy/insert affordance, no link to the assessment. Browser text selection is not blocked (cannot be done reliably and would harm accessibility); the guarantee is no in-app path from suggestion to assessment.

**R4 Concerns.** Heading "Potential concerns". Each concern: label (mission check name via `concernLabels.ts`) + explanation. Mapping, mirroring SP02 `CONCERN_TYPES` order and mission checks 1-12: Claim support; Contradictory evidence; Wrong person or source attribution; Timeframe mismatch; Negation reversal; Certainty inflation; Frequency or severity inflation; Context stripping; Question mistaken for an answer; Correction ignored; Conflicting accounts flattened; Unsupported causal links. A drift test asserts the map has exactly one entry per `CONCERN_TYPES` value; an unknown type (future minor version) falls back to the raw value, humanised.
- A concern is a toggle button only if at least one of its `evidence_ids` resolves to a **placeable** excerpt of this claim. Otherwise it is plain text (e.g. `evidence_ids: []`, as in the example's unsupported_claim concern, or dangling ids).
- Click: that concern becomes active; excerpts whose id it cites get an "emphasised" class, all others a "dimmed" class. Click again, or click another concern, to change/clear. `aria-pressed` reflects state. Dimmed excerpts stay fully readable and expandable (reduced opacity only, contrast stays >= 4.5:1 for text).
- Dangling ids are ignored silently (SP02 D5); never hide or throw.

**R5 Excerpts.** Source: `orderEvidence(request, claim, check)` -> ordered placeable evidence + `unplaceable`. For each, `walkSpan(request, ev.span, 'transcript')` gives segments, giving `firstTurn`/`lastTurn` for `buildChunks`. State: `expansion: Record<evidenceId, {up, down}>`, all zero initially. Output chunks are the render unit (D3).
- **Turn row**: header = `speaker`, then ` · role` only if `role` present, then right-aligned `timestamp` exactly as supplied (text node, unparsed) else `#<array index>` (0-based, the same index the contract uses) (D6). Body = turn text split at highlight boundaries via `sliceCodePoints`; highlighted slice normal, remaining parts of a span turn dimmed; a context-only row (no highlights, from expansion) is rendered in a lighter "context" style with no role border.
- **Excerpt marker**: on the first highlighted row of each excerpt, a chip with the role label text ("Supporting" / "Contradicting" / "Qualifying") and the role-coloured left border on every row it highlights. SP01 defines no role icon, so the chip text is the non-colour cue; the left-border style may also vary by role if SP06 adds one.
- **Note**: if `note` present, rendered after the excerpt's last highlighted row, prefixed "Audit note (paraphrase, not a quote):", italic, no quotation marks, visually distinct from transcript text.
- **Cross-turn**: one excerpt, contiguous rows; empty turns render a header row with an "(empty turn)" body.
- **Shared turns** (two excerpts highlight one turn): see D4.
- **Expansion controls** (D5): per chunk edge, `Show 3 more turns above (N hidden)` / `... below`. Between two chunks, one gap control with both directions. `hiddenAbove/hiddenBelow === 0` removes the control. Click increments `up` of the chunk's `topExcerptId` or `down` of `bottomExcerptId`, so one click adds at most 3 turns; the "N hidden" count is from `buildChunks`.
- **Unplaceable evidence** (own span out of range): after the placeable excerpts, a compact card per item: role label, the note if present, and "Position outside the supplied interview - excerpt withheld." No slicing attempted; never in `buildChunks`. Concern emphasis does not target it.

**R6 Empty and special states.**
| Claim | Show |
|---|---|
| `out_of_scope` | `out_of_scope_reason` in a labelled block; no concerns section content (schema forbids concerns), no excerpts section |
| `insufficient_evidence`, evidence `[]` | Excerpts section with "No excerpt in the supplied interview." plus the R2 line |
| Other verdict, evidence `[]` or all unplaceable | "No excerpts to show." (all-unplaceable still lists the withheld cards) |
| `concerns: []` | Concerns section omitted, not "no concerns" (mission: absence of concerns is not correctness) |

**R7 Text safety.** All transcript and note strings via React text nodes only (no `dangerouslySetInnerHTML`, no markdown). `white-space: pre-wrap` so original line breaks survive. Every string displayed as quote comes from `sliceCodePoints`/`walkSpan`.

**R8 Tests** (Vitest + Testing Library, jsdom per file): order of sections for the example `c-contradicted`; verdict badge has icon + label; suggestion box absent for `null`, present with heading otherwise, and contains no button; concern click emphasises `e-denial` and dims others, second click clears, concern with empty/dangling ids is not a button; excerpts in transcript order even when `evidence` array is reversed; `c-partial` renders turns 2 and 3 as one excerpt with the dim/highlight split at char 45; timestamp shown verbatim, `#4`-style when absent; note rendered with the paraphrase prefix; expand adds exactly 3 turns, merges with a neighbouring excerpt without duplicating a turn, and hides at transcript bounds; emoji turn highlight via a mutated clone; flagged evidence -> withheld card and no throw; `insufficient_evidence` with `[]` and `out_of_scope` states; selecting another claim resets concern and expansion; `concernLabels` drift test.

## Architecture
```
ClaimDetail (key=claim.id)
 |- VerdictBadge        (SP01 tokens)
 |- SuggestionBox, ConcernList (activeConcern state)
 |- ExcerptList (expansion state)
      orderEvidence -> walkSpan -> buildChunks -> ChunkView -> TurnRow (+ Note, ExpandControl)
```
`ClaimDetail` is pure with respect to props plus two `useState`s; chunk computation is a `useMemo` over `(claim, request, check, expansion)`. Only `src/contract` is called for positions.

## Decisions
| # | Decision | Choice | Alternatives considered | Why |
|---|---|---|---|---|
| 1 | State reset on claim change | Reset concern emphasis and expansion (`key={claim.id}`) | Persist expansion per claim in app state | Stepping through claims should give a predictable, compact view; keeps SP04 state minimal; reviewers rarely return mid-session |
| 2 | Prop shape | `{claim, request, check}` | `{claim, request, spanOutOfRange}` | Needs per-evidence flags from SP02 (`orderEvidence`); boolean is derivable |
| 3 | Render unit | Merged chunks from `buildChunks`, role chip per excerpt | One independent block per excerpt (duplicates shared turns) | Required: a turn is never shown twice |
| 4 | Shared turn, different roles (resolves SP02 open item) | Split the turn text at every highlight boundary; a segment under one excerpt gets that role's tint; under two gets a neutral highlight with one 3px underline per role colour; the left border becomes stacked stripes (one per role, in excerpt order); each role's chip is placed on the excerpt's first row and also lists the role names for a shared row | Last-wins; first-wins; render the turn twice | Never hides a role, never duplicates a turn; underline stacking stays legible with colour + the chip text as backup |
| 5 | Expand controls | GitHub-style rows at chunk edges and gaps; click = +3 for the owning excerpt | Per-excerpt buttons only; one global control | Matches locked model; edge ownership comes straight from `topExcerptId`/`bottomExcerptId` |
| 6 | Turn number | `#<0-based array index>` | 1-based | Matches the contract's position index; no invented numbering (see [OPEN]) |
| 7 | Concern interactivity | Button only if it cites a placeable excerpt | Always a button | A no-op click misleads; the example itself has an empty `evidence_ids` |
| 8 | Suggestion copy | No affordance, selection not blocked | `user-select: none` | Can't truly prevent copying; hostile to a11y; the rule is about in-app apply |
| 9 | Unplaceable evidence | Withheld card with role + note | Drop silently; show claim-level flag only | Reviewer should know evidence exists; note is not a quote so it is safe to show |
| 10 | Concern label source | Local map mirroring mission check names | Humanise enum (`question_as_answer` -> "Question as answer") | Locked: mission wording |

## Risks / Open Questions
- [OPEN] Shared-turn painting (D4) is a design on paper; confirm it reads clearly at SP06 with the two-role fixture, adjust visuals only.
- [OPEN] Turn number base: 0-based `#index` vs 1-based for reviewers; 0-based chosen to match the contract. Confirm with user.
- [RESOLVED: PRD 04 mounts `ClaimDetail` in `RightPane` with `check={analysis.checks[claim.id]}`] SP04 supplies `check`.
- [OPEN] Very long single turns (thousands of chars) make an excerpt tall; no truncation is planned (truncation would hide evidence). Revisit if SP06's long fixture is unwieldy.
- [DEFERRED] Scroll-to-excerpt on concern click (emphasis only for v1).
- [DEFERRED] Persisting expansion across claim changes.
- [RESOLVED: ignore] Dangling `evidence_ids` and duplicate evidence ids are tolerated (SP02 D5).
- [RESOLVED: withheld card] Out-of-range evidence span never sliced.

## Acceptance Criteria
- Example `c-contradicted`: badge (icon+label), explanation, suggestion box with heading "Suggestion — not applied", two concern buttons, one Contradicting excerpt (turn 1) with note.
- Example `c-partial`: turns 2 and 3 form one Qualifying excerpt; turn 3 highlights code points 0-45 and dims the rest; no duplicated turn.
- Clicking a concern dims non-cited excerpts; clicking again restores.
- `c-insufficient` shows "No excerpt in the supplied interview."; `c-oos` shows its reason and no excerpts.
- One click on "above" adds exactly 3 turns (or fewer at index 0); two nearby excerpts merge without repeating a turn.
- Flagged-span fixture claim renders, with the warning strip and withheld cards; no exception.
- Selecting a different claim clears emphasis and expansion.
- No button/handler can write to the assessment or copy the suggestion; no `dangerouslySetInnerHTML` in `claim-detail/` (lint rule or grep test).
- `npm test`, `lint`, `typecheck` pass; `docs/contracts/` unchanged.
