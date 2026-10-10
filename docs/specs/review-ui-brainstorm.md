# Review UI: brainstorm handoff

Status: **draft, not yet decided.** Starting point for the next brainstorm/dev-flow session on the visual review tool. The data contract it renders is in [../contracts/](../contracts/README.md).

## Already decided (from the contract brainstorm)

- Two panes. **Left:** the clinician's reasoning (assessment sections). **Right:** transcript excerpts.
- Selecting a claim on the left highlights its evidence on the right (mission: supporting, contradicting, qualifying).
- The frontend loads the same input file the backend saw. Response spans are `{index, char}` positions, no quote text, so the frontend slices the input itself.
- Positions count Unicode code points; slice with `Array.from(text)`. `end` is exclusive.
- Claims never overlap, so left-pane highlighting is flat.
- Each claim has a `verdict` (colours the left pane) and each evidence item a `role` (colours the right pane).
- `out_of_scope` claims are highlighted too, so the left pane has no unexplained gaps.
- `suggested_revision` is shown labelled as a suggestion and never applied.
- Schema failure: show an error, never a half-drawn audit. A single out-of-range span: render the claim with a warning badge.
- `label` and `score` are display-only grouping; never audited.

## Proposed colours (to settle)

| Meaning | Proposal |
|---|---|
| Verdict `supported` / `partially_supported` / `contradicted` | green / amber / red |
| Verdict `insufficient_evidence` | grey dashed outline (not the same as wrong) |
| Verdict `out_of_scope` | neutral hatched |
| Evidence `supporting` / `contradicting` / `qualifying` | green / red / amber |

## Open questions for the visual round

1. Layout: are sections stacked in one scroll, or tabbed by domain?
2. How does a claim list/selector work: inline click on highlighted text, a findings list, or both?
3. "Expand above/below": how many turns per click, and is the selected excerpt kept visually distinct?
4. Where do concerns (type plus explanation) appear: popover, side panel, or under the claim?
5. How are multiple evidence excerpts for one claim navigated (next/previous)?
6. Is colour alone enough? Add icons or patterns for accessibility.
7. Warnings and `partial` status: banner, per-section badge, or both?
8. Filter by verdict or concern type in v1, or cut?
9. Stack and tooling (framework, how the input and response files are loaded).
