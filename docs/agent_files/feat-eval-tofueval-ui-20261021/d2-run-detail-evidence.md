# D2 task 6 — RunDetail scoring lifecycle

Implemented the standalone `RunDetail` component with `api`, `runId`, `onOpenItem`
and `onBack` props. It composes MetricsTable, ItemList and RunInfoBlock, shows selected
run identity/state/failures and optional run-level failure text, and performs no audit
request. EvalApp wiring remains task 10.

Run and metrics reads start independently. A missing-metrics 404 is the client's normal
null result. Pending/running scoring shows `Scoring...` and disables Re-score. A single
sequential usePolling loop stops at done/failed and triggers a fresh metrics read after
a scoring transition. Re-score starts a new tagged polling generation so the old terminal
snapshot cannot stop the new loop; stale metric rows stay hidden until refetched.

Failed scoring and done-with-missing-metrics have explicit messages. Run state running
also disables Re-score. API errors preserve messages/details, unavailable-server errors
use ServerBanner with Retry, and three missed polls show the lost-contact banner while
polling continues. Keyed run changes abort previous work; in-flight rescore requests
are also cancelled on unmount. A ref lock blocks duplicate Re-score POSTs.

## Verification

All commands ran in `frontend/`, using injected fetch and fake timers:

```text
npx vitest run src/eval/RunDetail.test.tsx
 Test Files  1 failed (1)
      Tests  9 failed (9)
# Initial empty component: composition, scoring, errors and request-lifetime behavior absent.

# After implementation, including two further request/missing-data cases:
npx vitest run src/eval/RunDetail.test.tsx
 Test Files  1 passed (1)
      Tests  11 passed (11)
   Duration  2.45s

npm test && npm run typecheck && npm run build
 Test Files  42 passed (42)
      Tests  537 passed (537)
   Duration  16.37s
> tsc --noEmit -p .
> tsc --noEmit -p . && vite build
vite v8.3.4 building client environment for production...
✓ 163 modules transformed.
✓ built in 346ms
(exit 0)

git diff --check
(no output; exit 0)
```

Tests cover completed composition/navigation, pending→running→done and fresh metric
requests, rescore after an old terminal response, actual refreshed metric values, 409
message/detail, failed scoring/run error, missing metrics, running-run disable, three
misses/recovery/Retry, nonoverlap, late old-id responses, duplicate rescore prevention
and unmount cancellation of polls/metrics/rescore.

No ItemDetail, gold, EvalApp, protected review components, audit contracts or backend
files changed. No live provider calls, real-data downloads, browser checks or live
servers ran. Only task 6's source tracking cell was updated.
