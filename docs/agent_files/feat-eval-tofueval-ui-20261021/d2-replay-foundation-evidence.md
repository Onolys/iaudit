---
status: done
summary: D2 replay foundation tasks 1 and 2, offline verification evidence.
date: 2026-10-21
---
# D2 replay foundation

Worktree: `/root/projects/iaudit/.worktrees/feat/eval-ui-replay-foundation`
Branch: `feat/eval-ui-replay-foundation`
Base: `5a17804fec486115a28ef4e1bd922166d883de66`

## Task 1

Optional Header upload controls and ErrorScreen file action; exported `checkAuditResponse` preserves Audit response checks and error mapping. The existing audit tests are unchanged apart from added helper tests.

Red: `npm test -- --maxWorkers=2 src/app/Header.test.tsx src/transport/screens.test.tsx` exited 1: 2 failed, 31 passed; upload and choose-file buttons remained visible. `npm test -- --maxWorkers=2 src/transport/runAudit.test.ts` exited 1: 2 new tests failed because `checkAuditResponse` did not exist, 23 existing tests passed.

Green commands, in frontend:

```text
npm test -- --maxWorkers=2
Test Files 31 passed (31)
Tests 442 passed (442)

npm run typecheck
> tsc --noEmit -p .
(exit 0)

npm run build
> tsc --noEmit -p . && vite build
160 modules transformed.
✓ built in 357ms
(exit 0)
```

Setup used a local ignored node_modules symlink to the existing feature worktree dependencies; no installs or downloads. One initial setup command used the wrong working directory and unavailable `python`; rerun successfully from repository root with `python3` before tests were written.

Protected review components, contracts, backend/eval and D1 files are untouched. Only D2 task 1 bookkeeping changed. No live providers, browser checks, downloads, push or merge.


## Task 2

Added pure `eval/buildLoadResult.ts`: request validation, shared parsed-response checks, analysis, `source: "service"`. Tests import the actual contract request/response JSON pair and verify all five verdict counts, stale 1.0.0 rejection, malformed-response issues, request-first validation, request ID mismatch and no fetch/JSON.parse.

Red: the initial test-first run failed because the new module did not exist. The first implemented run exposed a test expectation typo (`outside_audit_scope` instead of the fixture's `out_of_scope`); corrected after inspecting the example. To verify behavioral failures rather than relying on missing-module errors, a temporary missing-behavior implementation returning `config_missing` made all six tests fail with assertion errors (exit 1). Restoring the implementation made all six pass (exit 0); no temporary mutation remains.

```text
npm test -- --maxWorkers=2
Test Files 32 passed (32)
Tests 448 passed (448)
(exit 0)

npm run typecheck
> tsc --noEmit -p .
(exit 0)

npm run build
> tsc --noEmit -p . && vite build
160 modules transformed.
✓ built in 361ms
(exit 0)

npm test -- --maxWorkers=2 src/eval/buildLoadResult.test.ts
Test Files 1 passed (1)
Tests 6 passed (6)
(exit 0, after mutation restoration)

git diff --check
(exit 0)
```

## Commits and scope

- Task 1: `edccb847d7ebbfbec7bb281a73d35cbd2ea200f6` — `02-results-and-items: Task 1 — shared replay controls and response checks`.
- Task 2: the commit containing this final evidence update — `02-results-and-items: Task 2 — build saved-item replay results`. Resolve with `git log -1 --format=%H -- frontend/src/eval/buildLoadResult.ts`.

Only D2 task 1 and task 2 status cells were changed in the source task list under the delegated bookkeeping exception. Artifacts reuse the explicitly assigned feature-branch artifact folder. No implementation scope deviations; no owner actions required for these two tasks. D2 tasks 3–11 remain untouched. The forbidden review files, contracts/backend/eval and D1 files remain unchanged from the base.
