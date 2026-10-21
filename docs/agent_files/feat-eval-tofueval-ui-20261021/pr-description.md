Adds the TofuEval adapter with pinned local downloads, schema-valid requests, frozen sentence projection, metrics, paper references, and integrity reporting. Original Five and Model-Extra results stay separate; balanced accuracy is undefined when either class is absent.

Adds the initial Eval UI: proxy/config, typed API client, schema-checked fixtures, polling hook, shell, Audit/Eval toggle, and run form with estimates. This PR is draft: run lifecycle and the runs/results/items/replay/comparison views remain unimplemented (D1 tasks 8–10 and all D2, 14 tasks). The Run button does not yet start a run.

Validation:

- Integrated frontend: 437 tests passed; typecheck and production build passed.
- Eval: 753 tests passed; required Ruff checks passed.
- Backend: 1,094 tests passed; required Ruff check passed.
- Project C full review: [all three personas PASS](https://github.com/Onolys/iaudit/blob/feat/eval-tofueval-ui/docs/agent_files/feat-eval-tofueval-ui-20261021/review-C-2026-10-21-final.md).
- Project D full review pending.
- `git diff --check` clean.

Continue from the source [D1 task list](https://github.com/Onolys/iaudit/blob/feat/eval-tofueval-ui/docs/agent_files/eval-ui-20261020/01-eval-shell-and-runs/TASKS.md) and [D2 task list](https://github.com/Onolys/iaudit/blob/feat/eval-tofueval-ui/docs/agent_files/eval-ui-20261020/02-results-and-items/TASKS.md).

No live provider calls, real dataset downloads, real-browser checks or live smokes were performed; owner checks are deferred.
