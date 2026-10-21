# Suggested title

Add TofuEval evaluation and initial Eval UI

# Draft PR body

Adds the TofuEval evaluation adapter, gold/projection rules, metrics, paper reference cells, and integrity reporting. Project C's 17 implementation tasks are complete and its final three-persona review is PASS after the balanced-accuracy fix.

Adds the initial Eval UI through D1 tasks 1–7: eval proxy/config, typed API client, schema-checked fixtures, sequential polling hook, EvalApp shell, Audit/Eval toggle, and RunPanel form/estimate. This is the user-requested stopping checkpoint and Project D is incomplete.

The default RunPanel button is not yet wired to start/download/progress/abort/resume. D1 tasks 8–10 and all 11 D2 tasks remain todo (14 tasks): run lifecycle, runs list, UI reference docs, and the results/items/replay/comparison work. Task 8 also owns the actual mid-run-toggle test and additive optional run-error eval API integration. Keep this PR draft pending the remaining implementation and review.

Validation:

- Final integrated frontend: 437 tests across 30 files passed; `npm run typecheck` passed; `npm run build` passed (160 modules, built in 291ms).
- Project C final eval gate: 753 tests passed; required Ruff checks clean.
- Unchanged backend gate at `01a694b`: 1,094 tests passed; required Ruff check passed.
- `git diff --check` clean.
- Project C review range `f7a4640...2cff97c`: Bug Hunter, Security, and Architect PASS; the earlier absent-class balanced-accuracy finding is resolved.

No live LLM/provider calls, real dataset downloads, live smoke runs, or real-browser checks were performed. Owner checks remain deferred. Project D code review base is `2cff97c`; the Project C PASS does not claim a completed Project D review.
