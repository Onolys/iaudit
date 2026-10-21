# D2 review fix — Refresh item results after scoring

Implemented on isolated linked worktree `fix/eval-item-refresh`, based on code commit
`34041b4ea70e25aee9dde06c9537bd8da03baf6e`. The feature worktree and its docs work were
not edited. No task statuses changed.

## Root cause and fix

`RunReader.items` serves raw saved-file rows while scoring outputs are unavailable:
gold/prediction/match are null, and a mismatch filter has no rows. RunDetail refreshed
metrics after terminal scoring but ItemList only fetched on api/run/filter/retry changes.
Its already mounted raw or empty page therefore remained stale after scoring and rescore.

Added an optional `ItemList.refreshKey` dependency and passed RunDetail's existing
terminal-scoring/rescore metrics revision. This refreshes both result consumers without
remounting the item list: the current filter is preserved, previous rows remain dimmed
while loading, and the existing request cancellation/stale-response guard applies.
Production changes are three added/replaced lines across ItemList and RunDetail.

## Regression evidence

All commands ran from the isolated worktree's `frontend/`, using injected fetch and
fake timers. The fake API follows the real raw-file fallback before returning scored
rows after terminal scoring.

```text
npx vitest run src/eval/RunDetail.item-refresh.test.tsx
 Test Files  1 failed (1)
      Tests  3 failed (3)
# Before fix: no item reload/dimming, missing scored mismatch after scoring and rescore.

npx vitest run src/eval/RunDetail.item-refresh.test.tsx src/eval/RunDetail.test.tsx src/eval/ItemList.test.tsx
 Test Files  3 passed (3)
      Tests  21 passed (21)
   Duration  2.66s

npm test && npm run typecheck && npm run build
 Test Files  45 passed (45)
      Tests  553 passed (553)
   Duration  19.58s
> tsc --noEmit -p .
> tsc --noEmit -p . && vite build
vite v8.3.4 building client environment for production...
✓ 180 modules transformed.
✓ built in 322ms
(exit 0)

git diff --exit-code 2cff97c -- frontend/src/app/ReviewShell.tsx frontend/src/app/LeftPane.tsx frontend/src/app/RightPane.tsx frontend/src/app/reviewState.ts frontend/src/claim-detail/ClaimDetail.tsx
(no output; exit 0)
git diff --check
(no output; exit 0)
```

The three new regressions prove raw partial rows become scored rows with newly written
items; a selected mismatch filter changes from empty to a scored mismatch while staying
selected; and that filter refreshes again after Re-score. The first case also holds the
refresh response and checks the existing table remains visible with `aria-busy=true`.

No protected review code, audit contracts, backend files, or task tracking changed.
No live provider calls, data downloads, browser checks, pushes or merges were performed.
