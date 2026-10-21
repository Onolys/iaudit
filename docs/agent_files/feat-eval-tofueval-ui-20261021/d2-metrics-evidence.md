---
status: done
summary: D2 task 4 adds pure metrics and provenance views; 473 frontend tests pass.
date: 2026-10-21
---
# D2 metrics and run information

Worktree: `/root/projects/iaudit/.worktrees/feat/eval-ui-replay-foundation`  
Branch: `feat/eval-ui-replay-foundation`  
Task base: `19a298fe4e507f63ba660847fe39339d0624ce9c`

## Delivered

- `MetricsTable.tsx` accepts `{ report: MetricsReport }` and delegates all raw report reads to `toMetricRows.ts`. The normalizer preserves first-seen level/slice/metric order, combines primary and secondary policies, matches references by metric/level/slice and isolates policy-none entries.
- Values, n and CI appear side by side. `n_clusters` is in hover titles. Unavailable intervals show dashes with status hints. Missing policies show dashes.
- Reference rows follow their matching metric with `.is-reference`, fixed grey styling and the exact paper label; only the reference value is populated. Caveats use a closed `details` element. No ranking or value-based colors.
- `RunInfoBlock.tsx` accepts `{ run }`, showing commit/dirty state, nested persisted fingerprint models/prompt hashes (8 characters, full hash title), mapping, seed, optional tags, cost or unknown, optional token counts, mixed-fingerprint warning, saved warnings, and the exact test-split informational line with no actions.
- Styling is isolated in `metrics.css`; shared `eval.css` remains unchanged.

Read actual persisted shape: engine `_set_identity` stores `fingerprint = {models, prompt_hashes}`; server `Reader.detail` forwards it inside `run_info`. Run info rendering uses that shape, guards missing/null fingerprints and never assumes top-level models. API totals presently lack token fields; the pure component accepts optional input/output token totals and shows them only when supplied, including zero.

## Integration decision

B3 `FailureRate` and `Coverage` use **pairs** as n; TofuEval sentence/summary metadata also defines policy-none `unresolved_rate`. Pair counts cannot safely stand in for item counts. Orchestrator directed:

- Item failure sentence uses authoritative `report.items.failed` and `report.items.selected`.
- Policy-none entries become separately level/slice-labeled supplemental rates, keeping them out of paired metric rows. This also retains native unresolved-rate information.

This resolves a reporting ambiguity without changing API or metric calculations. A regression using 100 sentence pairs and 3 items proves the view reports 1 of 3 items, rather than 50 of 100 pairs.

## Test evidence

Tests were written first; initial focused run exited 1 because the new component modules did not exist. After implementation, 8 focused tests passed. The additional authoritative-count regression was written before the adaptation: focused MetricsTable run exited 1 with **2 failed, 4 passed**, showing rate-derived counts (1/3 instead of authoritative 0/99, and 50/100 instead of authoritative 1/3). After adapting the normalizer:

```text
npm test -- --maxWorkers=2 src/eval/MetricsTable.test.tsx src/eval/RunInfoBlock.test.tsx
Test Files 2 passed (2)
Tests 9 passed (9)
(exit 0)

npm test -- --maxWorkers=2
Test Files 35 passed (35)
Tests 473 passed (473)
(exit 0)

npm run typecheck
> tsc --noEmit -p .
(exit 0)

npm run build
> tsc --noEmit -p . && vite build
160 modules transformed.
✓ built in 314ms
(exit 0)

git diff --check
(exit 0)
```

Tests cover level/slice grouping, equivalent slice keys, primary/secondary alignment, policy-none isolation and supplemental labels, authoritative item counts, reference order/label/dashes, collapsed caveats, cluster titles, CI status dashes and valid interval rendering, missing policy, persisted provenance, shortened hashes/full titles, null/absent cost, missing fingerprint, mixed warning, optional zero tokens and test-split informational-only behavior.

## Scope and commit

New files: `MetricsTable.tsx`, `MetricsTable.test.tsx`, `RunInfoBlock.tsx`, `RunInfoBlock.test.tsx`, `toMetricRows.ts`, `metrics.css`. Only D2 task 4 status cell changed in source TASKS; this is the sole new evidence artifact. No existing D1 files, shared stylesheet, API types/schema, backend/contracts, protected review components or later task implementations changed.

One task commit: `02-results-and-items: Task 4 — render metrics and run provenance`. Resolve SHA with `git log -1 --format=%H -- frontend/src/eval/MetricsTable.tsx`.

All checks offline; no providers, downloads, real browser checks, pushes or merges. No owner-only actions for this task. Components remain intentionally unwired until later D2 tasks.
