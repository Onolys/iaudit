# Review UI brainstorm: visual audit viewer

Status: **complete brainstorm.** Recorded from [UI Brainstorming](https://app.party.build/issues/4). Not a normative spec. The user writes the PRD and spec from this file.

## TL;DR

A lightweight, read-only React + TypeScript + Vite app in `frontend/` that renders the v1 audit contract (`docs/contracts/`). The reviewer uploads one request file. The UI validates it, POSTs it to the backend, validates the response, and shows two panes:
- **Left:** the clinician's reasoning, with each claim underlined in its verdict colour.
- **Right:** the selected claim's verdict, explanation, suggestion, concerns, and GitHub-diff-style transcript excerpts.

A mock mode serves the static example pair, so the UI can be tested without a backend.

This file is that document: `docs/agent_files/ab-20261010-221456-a271e3e2/brainstorming.md`. It replaces `docs/specs/review-ui-brainstorm.md` and is the input for the PRD and spec.

## Problem

**What:** the audit (mission part 1) is JSON with only positions, no quotes. Nobody can read it unaided. The mission's part 2, "a basic visual review tool", has to connect each claim to its evidence in context:
- highlight the claim in the assessment
- highlight its supporting, contradicting, and qualifying excerpts in the interview

**For whom:** a single human reviewer (clinician or QA reviewer) on a desktop browser, inspecting one case at a time. The reviewer decides whether a concern is valid. The UI never decides and never changes the assessment.

## Inputs and sources

- [docs/mission.md](https://github.com/tejitpabari99/iaudit/blob/main/docs/mission.md): governing scope, the 12 checks, verdict meanings, and part 2 (the visual tool).
- [docs/contracts/README.md](https://github.com/tejitpabari99/iaudit/blob/main/docs/contracts/README.md): the request and response schemas, span rules, and consumer rules. Merged in [PR #3](https://github.com/tejitpabari99/iaudit/pull/3).
- Contract brainstorm session: [3163cdd9](https://app.party.build/session/3163cdd9-b441-415b-9ed5-b28498b7711b).
- Superseded draft: `docs/specs/review-ui-brainstorm.md` (removed when this file was written).

## Design

### 1. Data flow

1. The reviewer **uploads one file**: an `AuditRequest` in the contract format.
2. The UI validates it against `audit-request.schema.json` with **Ajv** (Draft 2020-12). If it is invalid, the UI lists the errors and sends nothing.
3. The UI sends **POST** to `VITE_AUDIT_URL` with the request as the JSON body. It is one synchronous call: no streaming and no job id. A loading state shows while it runs, with a cancel button.
4. The UI validates the response against `audit-response.schema.json`. It then checks:
   - `schema_version == "1.0.0"`
   - `request_id` echoes the request's
   - every span is in bounds against the **uploaded** request
5. The UI renders, and selects the first claim.

**Mock mode** (`VITE_MOCK=true`) skips the network. It returns the response that matches the uploaded request, read from `docs/contracts/examples/`. There is one pair today. Add more later, for example a long assessment, and a `partial` status with warnings.

### 2. Error handling (standard, POST)

Each case gets its own plain error screen or banner. Nothing is half-rendered.

| Case | Display |
|---|---|
| Uploaded file isn't JSON, or fails the request schema | "Invalid request file", plus the validation errors (path and message). Nothing is sent. |
| Network failure or CORS | "Couldn't reach the audit service." Retry button. |
| Timeout or user cancel | "Request timed out" or "Cancelled." Retry button. |
| HTTP 4xx | "Request rejected (status)", plus the body message if it has one. |
| HTTP 5xx | "Audit service error (status)." Retry button. |
| Response isn't JSON, fails the schema, or has the wrong `schema_version` | "Invalid audit response", plus the validation errors. No audit is shown. |
| `request_id` mismatch | "Response doesn't match this request." No audit is shown. |
| One span out of range | The claim still renders, with a warning badge. Its other highlights do not shift. |
| `status: partial` or `warnings[]` | A top banner listing the warnings. A section with `section_not_processed` gets a "Not processed" badge. |

### 3. Layout

- **Header:** upload control, case `request_id`, and the **overall verdict stats in one row** across all sections. Example: ✓ Supported 3 · ◐ Partial 1 · ✕ Contradicted 2 · ? Insufficient 1 · ▨ Out of scope 1.
- **Left pane:** one scroll. Each assessment section is a **card**:
  - **Sticky card header:** the `label` and the `score` chip. The chip is neutral and display only, never presented as an audit result.
  - **Three-dot menu (⋯)** at the card's top right. It opens that section's verdict counts.
- **Right pane:** the detail of the selected claim.

### 4. Left pane: claims

- The reasoning text is shown exactly as written. Gaps between claims are plain text.
- **Every claim is underlined in its verdict colour** and is clickable. The underline is prominent, about 2–3px. Hover thickens the underline and shows a pointer cursor.
- **The selected claim** also gets a **neutral background**, such as light grey or blue, until another claim is selected. The first claim is selected on load.
- **Counts as navigation:** clicking a verdict count, in the header row or in a card's ⋯ menu, selects the first claim with that verdict, within that scope. The right-pane header then shows ‹ 1 of N › to step through those claims.
- No keyboard shortcuts in v1.
- Claims never overlap, as the contract guarantees, so the underlines are flat.

### 5. Right pane: claim detail (top to bottom)

1. **Verdict badge:** icon, label, and colour.
2. **Explanation.**
3. **Suggested revision**, if it is not null: a box labelled "Suggestion — not applied". It is never applied, and it is not copyable into the assessment.
4. **Concerns:** each shows its type label (in the mission's wording) and its explanation. Clicking a concern emphasises the excerpts its `evidence_ids` cite, and dims the rest.
5. **Excerpts**, in **transcript order**, not grouped by role. Each excerpt shows:
   - a role label (Supporting, Contradicting, or Qualifying) and a left border in the role's colour
   - each turn's header: speaker, plus `role` if present, plus the `timestamp` exactly as supplied or otherwise the turn number (`#index`)
   - the exact span highlighted, with the rest of the span's turns dimmed, because a span can start mid-turn
   - the `note`, if present, as a paraphrase rather than a quote
   - cross-turn spans, such as a question followed by "yes", as one excerpt
6. **Empty states:**
   - `insufficient_evidence` with no evidence: "No excerpt in the supplied interview." Not the same as wrong.
   - `out_of_scope`: shows `out_of_scope_reason`, with no excerpts.

### 6. Expanding context (GitHub diff model)

- Each excerpt has **↑ expand** and **↓ expand** controls. Each click adds **3 turns**.
- Chunks **merge** when they touch or overlap, so the same turn is never shown twice.
- There is **no "expand all"** and no full-transcript mode.
- Expansion only slices the uploaded transcript array. No new contract fields are needed.

### 7. Visual encoding

Colour is never the only signal: there is always an icon and a label as well. Check the palette for colourblind safety during the spec.

| Meaning | Colour | Icon / pattern |
|---|---|---|
| `supported` | green | ✓ |
| `partially_supported` | amber | ◐ |
| `contradicted` | red | ✕ |
| `insufficient_evidence` | grey, dashed underline | ? |
| `out_of_scope` | neutral, dotted underline / hatched badge | ▨ |
| Evidence `supporting` / `contradicting` / `qualifying` | green / red / amber left border and highlight | role label text |
| Selected claim | neutral background | — |

### 8. Text and position rules (from the contract)

- Slice with code points: `Array.from(text).slice(start, end)`. `end` is exclusive.
- **Never display a quote that was not produced by slicing the uploaded input.** Never invent speakers or timestamps.
- Wording stays "potential concern" and "not substantiated by the supplied interview". It never alleges fabrication.

### 9. Stack and location

- `frontend/` at the repo root: React, TypeScript, and Vite.
- Ajv validates against the schemas in `docs/contracts/`, used directly as the single source of truth.
- Configuration: `VITE_AUDIT_URL` and `VITE_MOCK`.
- Test with the static examples first. The UI is a thin, fast visual layer over the output.

### 10. Doc relocation (done)

1. This file is `docs/agent_files/ab-20261010-221456-a271e3e2/brainstorming.md`, with the Issue content.
2. This folder's `README.md` matches `ab-20261010-205358-98cf6861/README.md`.
3. The old link is removed from `docs/specs/README.md`, and `docs/specs/review-ui-brainstorm.md` is deleted.

## Decision log

| Decision | Alternative rejected | Why |
|---|---|---|
| Deep classification | Bounded | New frontend; no UI exists |
| Doc goes to `docs/agent_files/<branch>/brainstorming.md` | Stay in `docs/specs/` | User call; follows the `AGENTS.md` convention |
| Read-only viewer; no logins | Review workflow, auth | Mission: the human judges; v1 stays narrow |
| One request-file upload; the UI POSTs it to the backend | Two-file upload; paste text | User call; uses the contract as-is |
| No new contract fields | Quote or context fields | Locked in PR #3 |
| Every claim underlined in its verdict colour; neutral background on the selected claim | Plain text with hover-only underline (22:26 answer) | User revised it at 22:33: more prominent, so problems stay visible |
| First claim selected on load | Empty right pane | The pane is never blank |
| Overall verdict stats in one header row; per-section counts in a ⋯ menu on the card | A filter bar | User call; counts double as navigation |
| Clicking a count jumps to that verdict's claims, with ‹ 1 of N › | A verdict filter that hides claims | Keeps the full reasoning readable |
| No keyboard shortcuts | j/k/n | User call |
| One scroll, with sticky section cards | Tabs per domain | User accepted |
| Right pane order: verdict → explanation → suggestion → concerns → excerpts | Excerpts first | User call |
| Excerpts in transcript order | Grouped by role | Order exposes corrections (check 10) and disagreements (check 11) |
| Show all evidence roles | Supporting only | The mission requires counterevidence |
| GitHub-diff expansion, 3 turns per click, merging chunks | Expand all; full-transcript mode | User call; YAGNI |
| Colour plus icon plus label | Colour only | Accessibility |
| Suggested revision labelled "not applied" | Hide it; make it applicable | Mission: proposals, not corrections |
| POST to `VITE_AUDIT_URL`, with standard error handling | Undefined transport | User call |
| Ajv for schema checks | Hand-written checks; zod duplicates | Supports Draft 2020-12 and reuses the contract files |
| React + TypeScript + Vite in `frontend/` | `web/`; an annotation framework | User call |
| Mock mode with static examples | A mock server | User call; lightest way to test |

## Non-goals (v1)

- Accepting, dismissing, or commenting on findings.
- Editing the assessment, or applying suggestions.
- Export or PDF.
- Filtering by concern type.
- Expand all, or a full-transcript mode.
- History, multiple cases, or saved sessions.
- Logins, multiple users, or mobile layouts.
- Keyboard shortcuts.
- Any score or diagnosis interpretation beyond the display-only `label` and `score` chip.
- Audio playback, or file formats other than the contract JSON.
- Contract changes.

## Open risks (with the cheapest test)

| Risk | Cheapest test |
|---|---|
| Code-point and UTF-16 slicing bugs misplace highlights | A unit test that slices the example plus an emoji-containing turn, and asserts the expected substrings |
| Long real assessments make the underlines visually noisy | Build a long example pair for mock mode and eyeball it |
| Verdict colours aren't distinguishable for colourblind users | Run the palette through a colourblind simulator; the icons and labels remain as a backup |
| Synchronous POST is slow in practice | Time the backend on one real-length case, and confirm the cancel button works |
| Endpoint path or CORS isn't agreed with the backend | Confirm the POST URL and CORS with the backend team before integration; mock mode unblocks until then |
| Frontend and backend schema copies drift | Ajv imports `docs/contracts/*.schema.json` directly; no copied schema |

## Open questions (for the PRD or spec)

- The exact palette hex values, and the underline styles.
- The exact header layout at narrow desktop widths.
- More mock example pairs: which cases to add first.

## Q&A (asked and answered)

**Round 0 (assumptions):**
- Read-only: yes.
- No logins: yes.
- The UI calls the backend with the contract input: yes.
- No new contract fields: yes.
- No quote that doesn't come from slicing: yes.
- The user writes the PRD and spec; this doc only records the brainstorm.

**Round 1:**

| Q | Asked | Answer |
|---|---|---|
| Q1 | How does data get in? | Upload one file, in the contract format. |
| Left pane | — | The user's own input: show the reasoning, claims clickable, hover underline. Later revised (see Round 2). |
| Q2 | Layout | One scroll with sticky section headers, plus a summary bar. Accepted. |
| Q3 | Claim selection | No keyboard shortcuts. First claim selected on load. Right pane: verdict, then explanation, evidence, concerns. |
| Q4 | Context expansion | GitHub model. |
| Q5 | Colour | Colour plus icon plus label. Accepted. |
| Q6 | Cuts | No responding to findings, export, concern filter, expand all, edits, or history. Non-goals accepted. |
| Q7 | Stack | Build our own with React + TypeScript + Vite. Schema validator left to the agent: Ajv. |
| Q8 | Risk | Keep it light and fast. Test with static examples. |

**Round 2:**

| Q | Asked | Answer |
|---|---|---|
| Q1 | Marking claims | Keep the neutral background for the selected claim. Also underline every claim in its verdict colour, more prominently. |
| Q2 | Summary bar | Keep it. A ⋯ menu at the section card's top right, plus overall verdict stats in one row at the top. |
| Q3 | Right pane order and empty states | Accepted. |
| Q4 | Transport | POST, with standard error handling for the basic errors. |
| Q5 | Mock mode | Accepted. |
| Q6 | Code location | `frontend/`. |
