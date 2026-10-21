# Projects C and D implementation run

Branch: `feat/eval-tofueval-ui`.
Base: `f7a4640466611d4d3576775c2bd0403b9600de9a` (updated `main`, Project B complete).

This folder indexes implementation, verification and review artifacts for Projects C
and D. Reuse it for all artifacts created on this branch. The original PRDs and task
lists remain the implementation contracts; tracking stays in those source lists.

| Plan | Scope |
|---|---|
| [Project C approved plans](../eval-tofueval-20261020/README.md) | TofuEval data/items and projection/metrics. |
| [Project D approved plans](../eval-ui-20261020/README.md) | Eval shell/runs and results/items views. |

## Current execution progress

Project C is complete offline with final review PASS. Project D is now implemented
and verified offline: all ten D1 and eleven D2 tasks are done, including the fourteen
tasks deferred at the earlier stopping checkpoint. Final independent Project D review
is pending; no final review verdict is implied by the implementation status.

The integrated frontend at `34041b4` passed 550 tests across 44 files, typecheck and
production build. Fresh Python validation passed 754 eval tests and 1,094 backend
tests, plus required Ruff checks. Broader eval dataset lint retains three pre-existing
synthetic-adapter E501 findings. The [final Project D code run](code-final-project-d-2026-10-21.md)
contains commit references, validation and approved integration decisions.

Owner-only checks remain deferred: real dataset downloads, live LLM/provider calls,
live smoke, real-browser checks and the future A1 stale-item check. No publication or
PR metadata update accompanies this final documentation task.

## Run artifacts

- [Historical execution log](code-2026-10-21.md) — append-only implementation and earlier checkpoint evidence.
- [Final Project D code run](code-final-project-d-2026-10-21.md) — fourteen deferred tasks completed, final offline gate and owner checks.
- [Replay foundation](d2-replay-foundation-evidence.md), [API/fixtures](d2-api-fixtures-evidence.md), [metrics/provenance and review fix](d2-metrics-evidence.md), [item list](d2-item-list-evidence.md).
- [Run detail](d2-run-detail-evidence.md), [gold](d2-gold-evidence.md), [item detail](d2-item-detail-evidence.md), [comparison](d2-comparison-evidence.md), [navigation flow](d2-navigation-evidence.md).
- [Paper-reference auxiliary task evidence](../feat-eval-tofueval-references-20261021-1430/README.md).
- [Item-row auxiliary task evidence](../feat-eval-tofueval-item-rows-20261021-1500/README.md).
- [Final Project C review](review-C-2026-10-21-final.md) — PASS from all three personas after the balanced-accuracy fix in `2cff97c`; all 17 source Project C tasks done.

## Historical stopping checkpoint — superseded

The earlier user-requested stopping boundary left D1 tasks 8–10 and all eleven D2
tasks deferred. At that point, frontend verification was 437 tests across 30 files,
and RunPanel only supplied the form/estimate. That boundary and its fourteen-task
count are historical; the current implementation above supersedes them. Historical
logs are preserved without rewriting their point-in-time statements.

- [Historical checkpoint PR body](pr-description.md) — the earlier published scope and validation; final review/publication updates are separate work.
- Existing [draft PR #30](https://github.com/Onolys/iaudit/pull/30), originally titled
  “Add TofuEval evaluation and initial Eval UI,” targets `Onolys/iaudit:main` from
  `feat/eval-tofueval-ui`. The earlier checkpoint was pushed to origin. This docs task
  neither pushes nor changes the PR.
- Historical connector note: the GitHub integration lacked repository write scope
  (HTTP 403, `Resource not accessible by integration`); draft PR creation used the
  existing authenticated GitHub CLI. The canonical repository is `Onolys/iaudit`
  (redirected from the existing origin).
