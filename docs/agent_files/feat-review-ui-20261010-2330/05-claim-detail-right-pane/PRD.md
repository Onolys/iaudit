---
status: draft
summary: React ClaimDetail component (right pane body) - verdict, explanation, suggestion box, clickable concerns, transcript-order excerpts with role styling and GitHub-style +3-turn expansion, plus empty and out-of-range states. MVP-trimmed.
date: 2026-10-10
---
# PRD: 05 Claim detail (right pane)

Repo/branch: iaudit / `feat/review-ui` · Depends on: 01-frontend-scaffold, 02-contract-core (composed by 04-review-shell-left-pane) · Owns: `frontend/src/claim-detail/` (components, `concernLabels.ts`, CSS, colocated tests)

## TL;DR
One component, `ClaimDetail`, renders everything about the selected claim: verdict badge, explanation, "Suggestion — not applied" box, concerns (click to emphasise cited excerpts), and transcript-order excerpts with role styling and +3-turn up/down expansion. Local UI state only (active concern, expansion counts); all position work via SP02.

## Problem
The reviewer decides here whether a potential concern is valid. Show exactly the uploaded words (sliced, never invented), keep roles/verdicts legible without colour alone, survive invalid positions, and never imply the suggestion was applied or that "no excerpt" means "wrong".

## Goals / Non-Goals
**Goals**: requirement order (badge, explanation, suggestion, concerns, excerpts); excerpts in transcript order, cross-turn span = one excerpt, exact span highlighted and rest of its turns dimmed; GitHub-diff expansion via `buildChunks`, no turn shown twice; graceful empty / out_of_scope / out-of-range states.

**Non-Goals**: NavStepper, left pane, app state (SP04); transport/errors (SP03); accept/dismiss/comment, copy/apply suggestion, export, concern filter, expand-all, full-transcript mode, keyboard shortcuts, scroll-to-excerpt, turn truncation, multi-role stripes; colours (SP01 tokens); contract changes.

## Requirements

**R1 Interface.** `ClaimDetail({ claim: Claim, request: AuditRequest, check: ClaimCheck })`, `check = analysis.checks[claim.id]` (SP04 passes it). Remounted with `key={claim.id}` so local state resets on selection change.

**R2 Header.** Verdict badge from SP01 `VERDICT_STYLE` (icon + label + colour). Explanation as plain text. For `insufficient_evidence`, line under it: "Not substantiated by the supplied interview. This is not the same as contradicted." If `check.spanOutOfRange`, warning strip: "A position returned for this claim does not fit the supplied input. Affected text is withheld; other content is unchanged."

**R3 Suggestion.** Only when `suggested_revision` is a non-null string: bordered box, heading "Suggestion — not applied", the text. No button, copy, or insert affordance; text selection not blocked.

**R4 Concerns.** Heading "Potential concerns"; omitted when `concerns` is empty. Each: label + explanation. Labels from `concernLabels.ts`, mission check names in `CONCERN_TYPES` order: Claim support; Contradictory evidence; Wrong person or source attribution; Timeframe mismatch; Negation reversal; Certainty inflation; Frequency or severity inflation; Context stripping; Question mistaken for an answer; Correction ignored; Conflicting accounts flattened; Unsupported causal links. Unknown type falls back to the raw value.
- A concern is a toggle button (`aria-pressed`) only if some `evidence_ids` entry is in `placed`; otherwise plain text (empty or dangling ids). Dangling ids ignored silently.
- Click: that concern is active; excerpts it cites get class `emphasised`, the others `dimmed` (reduced opacity, still readable and expandable). Click again or click another to clear/switch.

**R5 Excerpts.** `orderEvidence(request, claim, check)` → `{placed, unplaceable}`. For each placed item, `walkSpan(request, ev.span, 'transcript')` gives segments → `firstTurn`/`lastTurn` for `buildChunks({transcriptLength: request.transcript.length, excerpts, expansion})`. State `expansion: Record<evidenceId,{up,down}>`, initially 0. Chunks are the render unit (D3).
- **Turn row**: header = `speaker`, ` · role` only if `role` present, right-aligned `timestamp` verbatim if present else `#<0-based array index>` (matches the contract). Body split at highlight boundaries with `sliceCodePoints`: highlighted slice normal, rest of an excerpt's turns dimmed. Context-only rows (from expansion) in a lighter style, no role border. Left border uses the excerpt's own role colour (SP01 `ROLE_STYLE`).
- **Role chip** on each excerpt's first highlighted row: role label text ("Supporting"/"Contradicting"/"Qualifying") plus role colour.
- **Note**: if present, after the excerpt's last highlighted row, prefixed "Audit note (paraphrase, not a quote):", italic, no quotation marks.
- **Cross-turn**: one excerpt over contiguous rows; an empty turn shows "(empty turn)".
- **Shared turn (D4)**: a segment covered by two or more excerpts gets a neutral highlight; the left border and chip follow each excerpt's own role.
- **Expansion**: per chunk edge `Show 3 more turns above (N hidden)` / `below`; between chunks, one gap control with both directions. Hidden count 0 removes the control. Click increments `up` of `topExcerptId` or `down` of `bottomExcerptId` (+3 turns, clamped by `buildChunks`).
- **Unplaceable evidence**: after the placed excerpts, one line each: "Excerpt position out of range" + role label + note if present. No slicing; not in `buildChunks`.

**R6 Empty and special states.**
| Claim | Show |
|---|---|
| `out_of_scope` | `out_of_scope_reason` in a labelled block; no concerns, no excerpts section |
| `insufficient_evidence`, evidence `[]` | Excerpts section: "No excerpt in the supplied interview." (plus R2 line) |
| other verdict, nothing placed | "No excerpts to show." (plus any out-of-range lines) |

**R7 Text safety.** Transcript and note strings only as React text nodes (no `dangerouslySetInnerHTML`, no markdown); `white-space: pre-wrap`. Every displayed quote comes from `sliceCodePoints`/`walkSpan`; out-of-range evidence is never sliced.

**R8 Tests** (Vitest + Testing Library): section order for `c-contradicted`; badge has icon + label; suggestion box absent for `null`, present with heading and no button otherwise; concern click emphasises its cited excerpt and dims others, second click clears, empty/dangling-id concern is not a button; excerpts in transcript order with `evidence` reversed; `c-partial` renders turns 2-3 as one excerpt with the dim/highlight split at char 45; timestamp verbatim, `#<index>` when absent; note has the paraphrase prefix; expand adds exactly 3 turns, merges with a neighbour without duplicating a turn, hides at bounds; out-of-range evidence → one-line notice, no throw; `insufficient_evidence` with `[]` and `out_of_scope` states; two excerpts sharing a turn (inline data) → overlap segment neutral, no duplicate turn; changing `key` resets concern and expansion.

## Architecture
```
ClaimDetail (key=claim.id)
 |- VerdictBadge, SuggestionBox, ConcernList (activeConcern state)
 |- ExcerptList (expansion state)
      orderEvidence -> walkSpan -> buildChunks -> ChunkView -> TurnRow (+ Note, ExpandControl)
```
Pure given props plus two `useState`s; chunks via `useMemo`. Only `src/contract` computes positions.

## Decisions
| # | Decision | Choice | Alternatives | Why |
|---|---|---|---|---|
| 1 | State reset | `key={claim.id}` | Persist per claim | Simple, predictable |
| 2 | Prop shape | `{claim, request, check}` | boolean flag | `orderEvidence` needs the full `ClaimCheck` |
| 3 | Render unit | Merged chunks, role chip per excerpt | Block per excerpt | A turn is never shown twice |
| 4 | Shared turn | Overlap segment = neutral highlight; border/chip per own role | Stripes, multi-underline | MVP simplicity; no role hidden because chips remain |
| 5 | Expand controls | GitHub-style rows at edges/gaps, +3 | Global control | Matches locked model |
| 6 | Turn number | `#<0-based index>` | 1-based | Matches the contract |
| 7 | Concern button | Only if it cites a placed excerpt | Always | No-op click misleads |
| 8 | Suggestion copy | No affordance, selection not blocked | `user-select: none` | Unreliable, hurts a11y |
| 9 | Out-of-range evidence | One-line notice with role + note | Drop silently | Reviewer should know it exists |
| 10 | Concern labels | Local map of mission names | Humanise enum | Mission wording |

## Risks / Open Questions
- [RESOLVED: 0-based `#index`] Turn number base.
- [RESOLVED: neutral highlight for overlaps, no stripes] Shared-turn painting.
- [RESOLVED: no truncation in MVP] Long single turns.
- [RESOLVED: input is normalized English, no emoji] Unicode handling beyond code-point slicing.
- [RESOLVED: palette fixed in SP01 tokens] Colours.
- [RESOLVED: SP04 passes `check={analysis.checks[claim.id]}`] `check` supply.
- [RESOLVED: ignore] Dangling and duplicate evidence ids (SP02 D5).
- [DEFERRED] Scroll-to-excerpt on concern click; persisting expansion across claims.

## Acceptance Criteria
- `c-contradicted`: badge, explanation, "Suggestion — not applied" box, two concern buttons, one Contradicting excerpt (turn 1) with note.
- `c-partial`: turns 2-3 are one Qualifying excerpt; turn 3 highlights code points 0-45, rest dimmed; no duplicated turn.
- Clicking a concern dims non-cited excerpts; clicking again restores.
- `c-insufficient` shows "No excerpt in the supplied interview."; `c-oos` shows its reason and no excerpts.
- One "above" click adds exactly 3 turns (fewer at index 0); nearby excerpts merge without repeating a turn.
- `out-of-range` fixture claim renders with the warning strip and one-line notices; no exception.
- Selecting another claim clears emphasis and expansion.
- No handler writes to the assessment or copies the suggestion; no `dangerouslySetInnerHTML` in `claim-detail/`.
- `npm test`, `lint`, `typecheck` pass; `docs/contracts/` unchanged.
