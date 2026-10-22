---
status: done
summary: "NEEDS_CHANGES — 2 must-fix (all fixed on this branch)"
date: 2026-10-21
---

# Review — 2026-10-21 — Project C (eval-tofueval)

Scope: main @ ff4b69c   Personas: Bug Hunter, Security, Architect+Coverage

## Verdict: NEEDS_CHANGES

## Must-fix
- C-1 [Architect] backend/tests/test_prompt_leakage.py:52-64 — eval_texts() only scans *.json*; TofuEval CSVs (summ_sent, exp) in eval/data/tofueval/repo/factual_consistency/*.csv never scanned. C1 R11 partial.
- C-2 [Bug] eval/datasets/tofueval/item_rows.py:53-55 — unknown gold error-type spelling raises ValueError in mapping.applicable_allowed and aborts scoring of a whole (paid) run; pairs.py silently drops it instead. No validation at load (items.py:136).

## Notes (non-blocking)
- C-3 [Architect+Bug] eval/datasets/tofueval/download.py:187-197,203-222 — raw/tofueval.zip (non byte-stable GitHub archive) and timestamped manifest included in records → false "changed upstream" warnings copied to every run; Decision 12 says hash extracted files only.
- C-4 [Architect+Bug] src/iaudit_eval/scoring.py:233-235 + tofueval pairs.py — failures.by_reason.unresolved summed across all levels and also for item_failed items (1 scored+2 failed → unresolved 23).
- C-5 [Architect] items.py:186 has_gaps computed but never reported by C2 (Decision 7).
- C-6 [Architect] metadata.json per-type concern_not_in_mapping_<type> entries hardcoded; R6 says per concern type; no test ties them to enum minus mapped.
- C-7 [Security+Bug] assessment.py:12, transcripts.py:18-19 — validation via assert (stripped by -O).
- C-8 [Bug] projection.py:28-43 — scoring projects saved response onto offsets rebuilt from current CSVs without checking saved request assessment text matches.
- C-9 [Security] tofueval download.py:45,57-60 — no per-member size cap on zip extraction / line reads; malicious-archive behaviour untested; https→http redirect followed.

## Coverage
C: all met except C1 R11 leakage scan (partial → C-1), C1 Decision 7 has_gaps report (partial → C-5).
Tests at review time: eval 754 pass, ruff clean; frontend 553 pass, typecheck clean; tofueval 246 pass.

## Resolution
Owner decision: fix all findings (must-fix and notes). Every ID is fixed on branch feat/eval-review-taxonomy-v1, except where noted.
C-1 (63d66af), C-2 (a2507e1), C-3, C-9 (548bc2e), C-4 (5e30f41), C-5 (7ab539e), C-6 (15bf582), C-7 (95b3e76), C-8 (1eefd1c). C-5 added `has_gaps` to the item_row detail only; no slice reports it.

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
