# Projects C and D implementation run

Branch: `feat/eval-tofueval-ui`.
Base: `f7a4640466611d4d3576775c2bd0403b9600de9a` (updated `main`, Project B complete).

This folder indexes the implementation, verification, and review artifacts for Projects C and D. Reuse it for all artifacts created on this branch.

| Plan | Scope |
|---|---|
| [Project C approved plans](../eval-tofueval-20261020/README.md) | TofuEval data/items and projection/metrics. |
| [Project D approved plans](../eval-ui-20261020/README.md) | Eval shell/runs and results/items views. |

The original PRDs and task lists remain the implementation contracts. Task tracking stays with those task lists; branch execution notes and reviews belong here.

Owner steps remain deferred: real dataset downloads, live LLM/provider calls, live smoke runs, and real-browser checks. Agent verification uses fictional fixtures and offline tests.

## Execution progress

Phase: User-requested stopping checkpoint complete. Project C complete offline with final review PASS; owner checks remain. Project D remains incomplete.

- C1 data and items: complete; all eight source tasks done.
- C2 projection and metrics: complete; all nine source tasks done.
- Project D: D1 tasks 1–7 done; D1 tasks 8–10 and all 11 D2 tasks remain todo (14 remaining tasks), deferred at the stopping boundary. Code review base `2cff97c`.

## Run artifacts

- [Task evidence log](code-2026-10-21.md) — implementation commits, files, verification, and execution notes.

- [Paper-reference task evidence](../feat-eval-tofueval-references-20261021-1430/README.md) — preserved auxiliary branch execution artifacts.

- [Item-row task evidence](../feat-eval-tofueval-item-rows-20261021-1500/README.md) — preserved auxiliary branch execution artifacts.

## Review fix

- Done: the P2 balanced-accuracy fix is resolved in `2cff97c`; [final Project C review](review-C-2026-10-21-final.md) PASS from all three personas. All 17 source implementation tasks remain done. Owner checks remain deferred.

## Checkpoint handoff

Final integrated frontend: 437 tests across 30 files passed; typecheck and build passed; `git diff --check` clean. RunPanel currently supplies form/estimate only: its default button has no start/download/progress/abort/resume lifecycle wiring. Task 8 owns that wiring, the actual mid-run-toggle test, and optional run-error eval API integration. No live checks performed.

- [Draft PR body](pr-description.md) — reviewer-facing checkpoint scope, validation, and 14 deferred Project D tasks.
- Publication: `feat/eval-tofueval-ui` pushed to `origin`; canonical repository is `Onolys/iaudit` (GitHub redirect from the existing origin). Draft PR intended for `Onolys/iaudit:main`, titled “Add TofuEval evaluation and initial Eval UI”. D1 tasks 8–10 and all D2 remain pending.
- Draft PR creation blocked: the connected GitHub integration returned HTTP 403, `Resource not accessible by integration` (`FORBIDDEN`). No PR was created; no CLI fallback attempted after the access rejection. The reviewer-facing body above is ready for owner creation or connector access repair.
