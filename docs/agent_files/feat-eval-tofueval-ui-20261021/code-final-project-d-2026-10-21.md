---
status: done
summary: All fourteen previously deferred Project D tasks implemented and verified offline; final independent review pending.
date: 2026-10-21
---
# Final Project D code run — deferred task completion

Branch: `feat/eval-tofueval-ui`
Worktree: `/root/projects/iaudit/.worktrees/feat/eval-tofueval-ui`
Original branch base: `f7a4640466611d4d3576775c2bd0403b9600de9a`
Earlier stopping checkpoint: `5a17804fec486115a28ef4e1bd922166d883de66`
Integrated code verified before docs: `34041b4ea70e25aee9dde06c9537bd8da03baf6e`

All ten D1 and eleven D2 source tasks are now done offline. The earlier checkpoint
had already completed D1 tasks 1–7; this run completed its remaining fourteen tasks.
Final independent Project D review is pending. Project C's earlier final PASS remains
historical and does not substitute for that review.

## Fourteen completed tasks

| Sub-project/task | Implementation commit | Result and evidence |
|---|---|---|
| D1/8 RunPanel lifecycle | `3c890af` | Start/download/progress/abort/reattach, run errors and offline toggle coverage; [execution log](code-2026-10-21.md). |
| D1/9 RunsList | `9e2e479` | Resume state matrix, one active progress source, compare selection; [execution log](code-2026-10-21.md). |
| D1/10 Reference docs | `3a5ac8e` | Form/lifecycle/proxy/owner checks; [execution log](code-2026-10-21.md). |
| D2/1 Shared replay controls/checks | `edccb84` | Optional Header upload and ErrorScreen file action, shared parsed-response helper; [evidence](d2-replay-foundation-evidence.md). |
| D2/2 buildLoadResult | `a49c19d` | Pure saved-pair validation/analysis with service source; [evidence](d2-replay-foundation-evidence.md). |
| D2/3 API fixtures | `19a298f` | Existing wrappers audited; current-contract replay, metrics/provenance/gold/compare fixtures completed; [evidence](d2-api-fixtures-evidence.md). |
| D2/4 Metrics and provenance | `407e075`, fix `11b7aea` | Paired metrics, honest counts, paper evaluator labels, CI/provenance; [evidence](d2-metrics-evidence.md). |
| D2/5 ItemList | `9eb730a` | Filters, raw-ID navigation, retained dimmed rows, cancellation; [evidence](d2-item-list-evidence.md). |
| D2/6 RunDetail | `85c39f7` | Scoring/re-score lifecycle and errors; [evidence](d2-run-detail-evidence.md). |
| D2/7 GoldPanel | `a08d456` | Guarded native TofuEval gold and collapsed JSON fallback; [evidence](d2-gold-evidence.md). |
| D2/8 ItemDetail/FailedItem | `a391428` | Real ReviewShell saved replay, failed/stale/unmapped paths; [evidence](d2-item-detail-evidence.md). |
| D2/9 CompareView | `110091c` | Shared/zero comparisons, signed neutral deltas and open-in-A/B; [evidence](d2-comparison-evidence.md). |
| D2/10 Navigation | `34041b4` | Run/item/compare/back and full offline flow; [evidence](d2-navigation-evidence.md). |
| D2/11 Docs | This documentation commit | Reference, implementation, test coverage, concepts and indexes; source task statuses complete. |

Auxiliary replay/results work was integrated through `690b5db`; saved item detail
through `5d5ca88`. Each implementation task retained its own commit. The separate
paper-reference review correction preserves evaluator identity when references share
one paper source. The source [D1](../eval-ui-20261020/01-eval-shell-and-runs/TASKS.md)
and [D2](../eval-ui-20261020/02-results-and-items/TASKS.md) task lists remain authoritative.

## Approved integration decisions

- D1 already supplied D2's typed API wrappers. Task 3 retained them and added coverage
  and fixtures instead of duplicating the transport.
- Backend cross-dataset comparison returns HTTP 422 `invalid_request`, while the PRD
  anticipated 409. Preserve the backend; display either inline through generic API errors.
- Pair-based failure/coverage n can differ from item counts. Use report.items for the
  item failure sentence; show policy-none rates separately with level/slice labels.
- API-permitted unmapped detail names its scoring limitation, replays a saved valid
  response when present, and otherwise states no saved response is available.
- The current response pin remains 1.1.0. Rejecting stale 1.0.0 now, and saved 1.1.0
  after A1's future 1.2.0 pin, is accepted; no replay conversion layer was added.

The governing mission and protected review components remain unchanged. There are no
new diagnosis/scoring/protocol/file-format features. Model scoring behavior was not
changed by the UI work; Re-score operates on saved eval results.

## Final offline gate

Frontend evidence is the integrated task-10 run at `34041b4`, recorded in
[d2-navigation-evidence.md](d2-navigation-evidence.md):

```text
# frontend/
npm test && npm run typecheck && npm run build
Test Files 44 passed (44)
Tests 550 passed (550)
Duration 18.27s
> tsc --noEmit -p .
> tsc --noEmit -p . && vite build
180 modules transformed.
✓ built in 301ms
(exit 0)
```

This agent independently ran Python suites sequentially in the main feature worktree
with UV_OFFLINE=1, preventing dependency downloads. Backend/eval had no working diff;
the latest commit touching them was `3c890afd065ff2ca060a5ccc0152806d31159982`.

```text
# eval/
UV_OFFLINE=1 uv run pytest
754 passed in 46.16s
(exit 0, no skips)

UV_OFFLINE=1 uv run ruff check src tests datasets/tofueval
All checks passed!
(exit 0)

# backend/
UV_OFFLINE=1 uv run pytest
1094 passed, 1 warning in 20.69s
(exit 0, no skips)

UV_OFFLINE=1 uv run ruff check src tests eval
All checks passed!
(exit 0)
```

The backend warning is Starlette's existing httpx TestClient deprecation. No failing
environmental conditions occurred. Broader eval lint remains a known baseline:

```text
# eval/
UV_OFFLINE=1 uv run ruff check src tests datasets --output-format concise
datasets/synthetic/adapter.py:41:101: E501 Line too long (109 > 100)
datasets/synthetic/adapter.py:43:101: E501 Line too long (105 > 100)
datasets/synthetic/adapter.py:59:101: E501 Line too long (101 > 100)
Found 3 errors.
(exit 1; synthetic baseline only, unchanged)
```

Task 11 is documentation only; no additional test suite run is needed. Relative
links and `git diff --check` were checked for the final documentation change:

```text
Read-only relative-link and anchor validator
Validated 76 relative documentation links across 12 Markdown files
All relative links and section anchors resolve.
(exit 0)

git diff --check
(no output; exit 0)
```

 Historical execution logs retain their original counts and deferred-task
statements; current indexes point here for the superseding status.

## Owner checks still deferred

- Download the real dataset after license/source review and verify its local hashes.
- Launch the real stack with provider credentials; run a small paid pilot and live
  smoke, verify cost/cap/abort/resume behavior and `/eval-api/health` through Vite.
- In a real browser, close/reopen Eval during a run and confirm reattachment.
- Open a real TofuEval item against its source CSV; inspect metrics, gold and compare.
- Open the largest saved item and assess load time.
- After A1, confirm old 1.1.0 item replay fails while lists/metrics/compare remain usable.

No live providers, real dataset downloads, real browser checks or live smoke ran.
No push or PR metadata changes accompany this documentation task. Final independent
review and any resulting corrections remain before a final publication update.
