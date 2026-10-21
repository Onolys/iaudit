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

Phase: Project C complete offline with final review PASS; owner checks remain. Project D stopping checkpoint in-progress after the current tasks.

- C1 data and items: complete; all eight source tasks done.
- C2 projection and metrics: complete; all nine source tasks done.
- Project D: D1 tasks 1–6 done; task 7 (RunPanel form and estimate) remains in-progress. D1 tasks 8–10 and all D2 are deferred at the user-requested stopping boundary; Project D remains incomplete. Code review base `2cff97c`.

## Run artifacts

- [Task evidence log](code-2026-10-21.md) — implementation commits, files, verification, and execution notes.

- [Paper-reference task evidence](../feat-eval-tofueval-references-20261021-1430/README.md) — preserved auxiliary branch execution artifacts.

- [Item-row task evidence](../feat-eval-tofueval-item-rows-20261021-1500/README.md) — preserved auxiliary branch execution artifacts.

## Review fix

- Done: the P2 balanced-accuracy fix is resolved in `2cff97c`; [final Project C review](review-C-2026-10-21-final.md) PASS from all three personas. All 17 source implementation tasks remain done. Owner checks remain deferred.
