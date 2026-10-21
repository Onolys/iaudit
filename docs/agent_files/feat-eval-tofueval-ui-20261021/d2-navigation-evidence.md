# D2 task 10 — Eval navigation and complete offline flow

Replaced EvalApp's placeholder ViewSlot with real RunDetail, ItemDetail and CompareView.
The item view records its run/compare origin; comparison-origin items retain both run
ids and expose the exact `Back to comparison` action. Run-origin items return to their
run, and run/compare views return to the runs list.

Navigation unmounts the departing screen, cancelling its fetches and polling. Returning
to the list clears old local attachment/progress and scans the server again. This
avoids reattaching a previous resumed run when a different run is now active. D1's
single progress poller remains the only active list poller.

## Tests and verification

Commands ran from `frontend/` with real components, injected fake fetch, current
schema-validated fixtures and fake timers; global fetch throws if used:

```text
npx vitest run src/eval/mock-flow.test.tsx
 Test Files  1 failed (1)
      Tests  2 failed (2)
# Before wiring: placeholder run screen has no real detail, scoring or item controls.

# Final full-flow coverage:
npx vitest run src/eval/mock-flow.test.tsx
 Test Files  1 passed (1)
      Tests  3 passed (3)
   Duration  3.49s

npm test && npm run typecheck && npm run build
 Test Files  44 passed (44)
      Tests  550 passed (550)
   Duration  18.27s
> tsc --noEmit -p .
> tsc --noEmit -p . && vite build
vite v8.3.4 building client environment for production...
✓ 180 modules transformed.
✓ built in 301ms
(exit 0)

git diff --exit-code 2cff97c -- frontend/src/app/ReviewShell.tsx frontend/src/app/LeftPane.tsx frontend/src/app/RightPane.tsx frontend/src/app/reviewState.ts frontend/src/claim-detail/ClaimDetail.tsx
(no output; exit 0)
git diff --check
(no output; exit 0)
```

The flow starts a run, opens run detail, replays an item with gold and no upload,
returns through run/list, selects two runs, opens comparison, opens the saved item in
A and B, and returns to the same comparison pair. It asserts the respective item URLs
and zero calls to global fetch. Further cases verify cancellation of departed in-flight
list/scoring polls, exactly one list poller after returning, and replacement of a stale
resume attachment by the server's current active run. Existing shell and runs tests now
assert real view content rather than obsolete placeholders.

Only task 10's source tracking status was updated. Task 11 remains todo. No App/Audit,
protected review implementation, audit contract or backend changes; no provider calls,
real data downloads, real browser checks or live servers ran.
