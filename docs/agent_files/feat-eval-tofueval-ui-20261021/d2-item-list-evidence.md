---
status: done
summary: D2 task 5 adds filterable item list with stale-response protection; 480 frontend tests pass.
date: 2026-10-21
---
# D2 item list evidence

Worktree: `/root/projects/iaudit/.worktrees/feat/eval-ui-replay-foundation`
Branch: `feat/eval-ui-replay-foundation`
Task base: `407e075c5cf7514cc4ba2202e49780d632a715d1`

## Delivered and acceptance

`ItemList({ api, runId, onOpenItem })` requests all/mismatch/failed through one `listItems` call per filter with limit 10000 and no offset or pagination UI. Server `routes_run_reads.items` defines limit with Query ge=1 and no maximum, so the chosen limit exceeds the documented largest dataset (1777) without violating a server bound.

The table displays Item (`label ?? item_id`), Gold, Ours, Match (check/cross/dash), and a failed status chip. Clickable rows and explicit keyboard-accessible item buttons pass raw IDs once, including `.`, `-` and `--`. The exact empty message appears only after a successful empty response.

Filter reloads keep prior rows visible with an `.is-loading` opacity rule and `aria-busy`. Each effect owns an AbortController; cleanup aborts on filter/run changes and unmount, and the result handler ignores aborted requests even if an injected API disregards cancellation. Errors use existing EvalErrorMessage and inline Retry; successful retry replaces the error with rows. Old-run rows are hidden on run identity changes.

Styling is isolated in `item-list.css`; shared `eval.css` is untouched. No later task integration was started.

## TDD and verification

Tests were written before implementation; the initial run failed because the new module did not exist. Six initial focused tests then passed. Added successful Retry recovery coverage. A temporary mutation removing the cancellation guard made the stale-filter regression fail with an assertion that the old item returned; restored the real implementation before final verification.

```text
npm test -- --maxWorkers=2 src/eval/ItemList.test.tsx
Test Files 1 passed (1)
Tests 6 passed (6)
(exit 0, before additional retry-recovery test)

npm test -- --maxWorkers=2 src/eval/ItemList.test.tsx -t 'ignores a stale filter'
Test Files 1 failed (1)
Tests 1 failed | 6 skipped (7)
(exit 1, intentional temporary mutation)

npm test -- --maxWorkers=2
Test Files 36 passed (36)
Tests 480 passed (480)
(exit 0, restored implementation, all seven ItemList tests included)

npm run typecheck
> tsc --noEmit -p .
(exit 0)

npm run build
> tsc --noEmit -p . && vite build
160 modules transformed.
✓ built in 304ms
(exit 0)

git diff --check
(exit 0)
```

Tests use fake fetch with real evalApi validation, each filter/method/query, raw-ID callbacks, columns/match states/failed chip, exact empty text, visible/dimmed prior rows, a deliberately noncooperative injected API for stale response order, inline error/retry recovery and abort on unmount. No live network, providers, browser checks or downloads.

## Files and commit

New files: `frontend/src/eval/ItemList.tsx`, `ItemList.test.tsx`, `item-list.css`, and this evidence artifact. Only D2 task 5 status cell changed in the task list. Shared/protected review files, contracts, backend, API schema and D1 implementation files remain untouched.

One task commit: `02-results-and-items: Task 5 — add filterable item list`; resolve SHA with `git log -1 --format=%H -- frontend/src/eval/ItemList.tsx`.

No scope deviations, owner-only actions, push or merge. The auxiliary branch now contains D2 tasks 1–5 as individual commits and is ready for orchestrator integration.
