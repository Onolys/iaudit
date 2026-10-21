---
status: done
summary: D2 task 9 adds comparisons with shared counts, neutral deltas and item navigation; 487 tests pass.
date: 2026-10-21
---
# D2 comparison evidence

Worktree: `/root/projects/iaudit/.worktrees/feat/eval-ui-replay-foundation`
Branch: `feat/eval-ui-replay-foundation`
Task base: `9eb730a49cff15e86ce4af0450d3525a7fbfd196`

`CompareView({ api, aRunId, bRunId, onOpenItem, onBack })` requests the encoded compare route, displays run A/B labels and prominent `n shared = k`, and shows plain delta/disagreement tables. Delta rows include metric, level, slice, policy, A/B values, signed B-minus-A delta and CI only with `ci_status: ok`; unavailable CIs show status hints. No value-based styling, ranking or judgement. Each disagreement shows its item and differing pairs (level/unit/gold/A/B), plus `open in A` and `open in B` passing raw run/item IDs. Zero shared displays exact `No shared items` and no tables. Saved warnings are shown.

HTTP 409 and actual backend 422 API errors render inline through EvalErrorMessage; unreachable errors use existing ServerBanner with Retry. Requests abort on IDs/API changes and unmount; aborted callbacks are ignored even when an injected API disregards cancellation. Previous-pair results are hidden after prop changes.

## Tests and verification

Tests were written first; initial run exited 1 because the CompareView module did not exist. After implementation:

```text
npm test -- --maxWorkers=2 src/eval/CompareView.test.tsx
Test Files 1 passed (1)
Tests 7 passed (7)
(exit 0)

npm test -- --maxWorkers=2
Test Files 37 passed (37)
Tests 487 passed (487)
(exit 0)

npm run typecheck
> tsc --noEmit -p .
(exit 0)

npm run build
> tsc --noEmit -p . && vite build
160 modules transformed.
✓ built in 319ms
(exit 0)

git diff --check
(exit 0)
```

Coverage: normal saved comparison; route encoding; raw-ID open-in callbacks and Back; signed positive/zero/negative/null delta; CI status gating even when non-ok responses contain intervals; zero shared; both cross-dataset HTTP statuses; network Retry recovery; stale-pair response protection with noncooperative API; abort on unmount. All calls use fake fetch, no live network.

New files: `CompareView.tsx`, `CompareView.test.tsx`, `compare.css`, this artifact. Only D2 task 9 status cell changed. No main feature worktree, EvalApp, shared stylesheet, protected review files, contracts or backend changes.

Commit: `02-results-and-items: Task 9 — add run comparison view`; resolve SHA with `git log -1 --format=%H -- frontend/src/eval/CompareView.tsx`.

Only integration adaptation is the previously approved generic handling of HTTP 422 alongside PRD 409; backend behavior remains unchanged. No push/merge or owner-only checks.
