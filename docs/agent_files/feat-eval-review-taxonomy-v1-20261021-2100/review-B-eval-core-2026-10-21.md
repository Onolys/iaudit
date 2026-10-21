---
status: done
summary: "NEEDS_CHANGES — 4 must-fix (all fixed on this branch)"
date: 2026-10-21
---

# Review — 2026-10-21 — Project B (eval-core)

Scope: main @ ff4b69c   Personas: Bug Hunter, Security, Architect+Coverage

## Verdict: NEEDS_CHANGES

## Must-fix
- B-1 [Architect, also Bug] eval/src/iaudit_eval/server/manager.py:~649 + engine.py:328-331 — shutdown cancels in-flight audits immediately; B4 PRD says in-flight items finish within grace period. Paid responses discarded and re-sent on resume.
- B-2 [Bug, also D Bug/Architect] manager.py:193-195 — `score_state:"pending"` reported for terminal runs whose metrics are not current while no score task exists (after restart, interrupted at shutdown). Never resolves; UI shows "Scoring..." forever.
- B-3 [Bug, also Architect] manager.py:285-288 / ~567-570 `_observe` — refused resume (FingerprintChanged/SchemaVersionChanged) recorded as score_state "failed"; real cause never surfaced; metrics 404 because run.json rewritten.
- B-4 [Bug] engine.py:724-725 + :243 — capped run vs backend that never sends cost_usd fails cost_missing; resume keeps stored cap with no way to clear; every resume spends one more paid audit.

## Notes (non-blocking)
- B-5 engine.py:421-423 — cap/abort reached after last item stores aborted/aborted_cost though all items processed.
- B-6 store.py:293-301 — is_locked takes exclusive flock briefly; concurrent GET can make resume/start lock fail (409 / uncaught RunLockedError → 500 + orphan running dir).
- B-7 src/iaudit_eval/download.py:244,291 — downloading/failed status drops prior `files` records → TOFU drift detection lost after one failure.
- B-8 metrics/bootstrap.py:123 + 88-92 — ci null but ci_status "ok" when <90% resamples defined.
- B-9 engine.py:433-436 `_auto_score` ignores custom datasets root.
- B-10 client.py:124-127 — httpx.ConnectTimeout classified as timeout (not retried, not fatal on canary); should be network.
- B-11 B4 AC7 "no item ids in logs" conflicts with B2 R12 (engine logs filename-safe item_id).
- B-12 [Security] server/app.py:113-122 — bind check only in main(); `uvicorn --host 0.0.0.0` bypasses; Host-header check spoofable by non-browser client.
- B-13 [Security] src/iaudit_eval/download.py:186,255-260 — allows http://, follows redirects incl. https→http, no size cap.

## Coverage
B: all B1–B4 R/AC met except B4 AC3 shutdown-grace (partial → B-1), B4 AC7 logs (partial → B-11).
Tests at review time: eval 754 pass, ruff clean; frontend 553 pass, typecheck clean; tofueval 246 pass.

## Resolution
Owner decision: fix all findings (must-fix and notes). Every ID is fixed on branch feat/eval-review-taxonomy-v1, except where noted.
B-1..B-6, B-9 (be67f70), B-7, B-13 (c2abaed), B-8 (b81b3cb), B-10 (3afa25a, ca7b62f), B-12 (9be08ed). B-11 (doc conflict between B4 AC7 and B2 R12): no commit on the branch touches it; no code change was made, left as a documentation note.

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
