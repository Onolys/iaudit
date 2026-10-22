---
status: done
summary: "NEEDS_CHANGES — 3 must-fix (all fixed on this branch)"
date: 2026-10-21
---

# Review — 2026-10-21 — Project D (eval-ui)

Scope: main @ ff4b69c   Personas: Bug Hunter, Security, Architect+Coverage

## Verdict: NEEDS_CHANGES

## Must-fix
- D-1 [Bug+Architect] frontend/src/eval/RunDetail.tsx:130,155,195,207,263,303,315 — terminal run with never-resolving `pending` → "Scoring..." forever, polls 1 s forever, Re-score disabled (pairs with B-2). D2 R2 partial.
- D-2 [Bug] useRunLifecycle.tsx:215-251 — download poll reuses previous attempt's terminal data (retry shows old failure / fake ready); downloadError not cleared on dataset change (RunPanel.tsx:128).
- D-3 [Bug] RunPanel.tsx:65-82,95,129 — cap cleared on N/split/dataset change; Run clickable before new estimate → uncapped run (fail-open).

## Notes (non-blocking)
- D-4 evalApi.ts:56,116 — 10 s GET timeout; GET /compare re-scores with bootstrap, likely times out on full runs.
- D-5 useRunLifecycle.tsx:271-279 — abort can exceed 30 s POST timeout → false timeout error.
- D-6 ItemList.tsx:19 — limit 10_000, ignores page.total; silent truncation.
- D-7 RunInfoBlock.tsx:253 — raw float cost formatting.
- D-8 RunDetail.tsx:324 — item list doesn't refresh during a run.
- D-9 toMetricRows.ts:313 / MetricsTable.tsx:245-246 — all policy "none" metrics (TofuEval diagnostics) shown as failure bullets; need separate Diagnostics table.
- D-10 RunDetail.tsx:213 — running run shows "Scoring..." instead of progress.
- D-11 useRunLifecycle.tsx:254-270 — hook returns JSX `display`; move to component.
- D-12 [Security] evalApi.ts:110-117 — ids "." / ".." not refused client-side (server blocks; defence in depth).
- D-13 (from B-4) UI path to resume a cost_missing-failed run without cap.

## Coverage
D: all met except D2 R2 scoring state (partial → D-1).
Tests at review time: eval 754 pass, ruff clean; frontend 553 pass, typecheck clean; tofueval 246 pass.

## Resolution
Owner decision: fix all findings (must-fix and notes). Every ID is fixed on branch feat/eval-review-taxonomy-v1, except where noted.
D-1, D-6..D-10 (fbcee5a), D-2, D-3, D-5, D-11 (4cc0701), D-4, D-12 (dbb4bd4), D-13 (b05f45b).

Merge commits on the branch (`git log --oneline --merges main..HEAD`):
```
9e6b9e0 Merge a1/task6
6c773ae Merge fix/ui-lifecycle
8f9706f Merge a1/task4
9eae2fa Merge fix/eval-server-engine: review fixes B-1..B-6, B-9
dcd96a7 Merge fix/ui-results: review fixes
5ffcacd Merge fix/tofueval-scoring: review fixes
80d5f0e Merge fix/eval-misc: review fixes
65f6426 Merge fix/eval-downloads: review fixes
```

## Next step
None. Owner live checks remain.
