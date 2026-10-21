---
status: done
summary: D2 task 8 implements saved-item review and failed-item details; 536 frontend tests pass.
date: 2026-10-21
---
# D2 item detail evidence

Worktree: `/root/projects/iaudit/.worktrees/feat/eval-ui-replay-foundation`
Branch: `feat/eval-ui-replay-foundation`
Task base: `690b5dbb4f55f4c5b9d8873c470b5f2e44936488` (fast-forwarded from main feature before task 8; includes GoldPanel task 7).

## Delivered

`ItemDetail({ api, runId, itemId, onBack, backLabel })` fetches a saved item and shows a back bar and GoldPanel. Successful saved request/response pairs pass through pure buildLoadResult into the existing ReviewShell, keyed by JSON-encoded run/item identity; header carries run/item filename and request ID, source is service, with no file handler or upload controls. Existing review components are unchanged. No audit endpoint or model call is used.

Stale 1.0.0 or invalid saved responses show the existing ErrorScreen without a choose-file action. Failed items show GoldPanel and FailedItem, with no review shell. FailedItem displays supplied kind, HTTP status, error_code, message and at most 50 valid path/message issues, plus the remaining count; absent optional fields are omitted. It preserves the exact required retry-via-resume message.

Fetch errors use shared ServerBanner/Retry for network failures and inline EvalErrorMessage/Retry for API errors. Effect-owned AbortControllers cancel old resources and unmount; aborted callbacks are ignored even with noncooperative injected API calls. Old item data is hidden as IDs change.

## Unmapped integration adaptation

Inspected actual server `Reader.item_detail`: status comes from the saved record, whereas scoring creates unmapped item-row statuses separately in `scoring.py`. The API nevertheless permits `unmapped` details. Orchestrator approved explicit treatment: show `This item could not be mapped for scoring.`; replay a validated saved response if present; otherwise show `No saved audit response is available.` Do not invent a backend failure or claim a failed request can be fixed by resume.

## Verification

Tests were written first; initial run exited 1 because ItemDetail did not yet exist. After implementation, focused tests passed, then an additional unmapped-with-response test was added. Final offline checks:

```text
npm test -- --maxWorkers=2 src/eval/ItemDetail.test.tsx
Test Files 1 passed (1)
Tests 10 passed (10)
(exit 0)

npm test -- --maxWorkers=2
Test Files 42 passed (42)
Tests 536 passed (536)
(exit 0)

npm run typecheck
> tsc --noEmit -p .
(exit 0)

npm run build
> tsc --noEmit -p . && vite build
163 modules transformed.
✓ built in 304ms
(exit 0)

git diff --check
(exit 0)

git diff --name-only 690b5db -- frontend/src/app frontend/src/claim-detail docs/contracts eval frontend/src/eval/eval.css frontend/src/eval/evalTypes.ts
(no output)
```

Coverage: valid replay and gold, raw encoded item endpoint, Back callback, no upload/no audit service calls, failed fields/no shell, stale/invalid ErrorScreen, fetch Retry recovery, selection reset across item changes using real ReviewShell, stale response isolation, unmount cancellation, unmapped with/without response, and fifty-issue cap/absent failure fields.

## Files and commit

New files: `ItemDetail.tsx`, `FailedItem.tsx`, `ItemDetail.test.tsx`, `item-detail.css`, this artifact. Only source D2 task 8 status cell changed. No shared eval.css/types, main feature worktree, protected review components, backend or contract changes.

One task commit: `02-results-and-items: Task 8 — replay saved item details`; resolve its SHA with `git log -1 --format=%H -- frontend/src/eval/ItemDetail.tsx`.

No live providers, downloads, browser checks or push. The only merge performed was the explicitly requested initial fast-forward of main feature into this auxiliary branch. No later tasks started; ready for principal integration.
