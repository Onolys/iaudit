# Agent files

Branch-scoped agent artifacts, one folder per branch.

**Audience:** coding agents.

Put PRDs, task lists, reviews, plans, and notes for a branch in `docs/agent_files/<branch-name-timestamp>/`. Replace `/` in the branch name with `-`. Create the folder once per branch and reuse it.

| Folder | Purpose |
|---|---|
| [feat-backend-poc-20261011-0012](feat-backend-poc-20261011-0012/README.md) | Backend POC: FastAPI service for `POST /v1/audit` (contract 1.0.0) through prep, atomize, link, check, assemble; 8 sub-projects with PRDs and tasks. |
| [feat-review-ui-20261010-2330](feat-review-ui-20261010-2330/README.md) | Review UI v1 MVP: read-only React/TS/Vite viewer over the audit contract; 6 sub-projects with PRDs and tasks. |
| [users-codex-eval-investigation-20261020-035707](users-codex-eval-investigation-20261020-035707/README.md) | Evaluation research synthesis (benchmarks, TofuEval/PriMock scoring, recommendations); documentation only. |
| [eval-core-20261020](eval-core-20261020/README.md) | Project B: `run_info` contract 1.1.0, eval engine, metrics/scoring, eval API server + dev script (4 PRDs). |
| [eval-tofueval-20261020](eval-tofueval-20261020/README.md) | Project C: TofuEval data/items and gold projection/metrics plug-in (2 PRDs). |
| [eval-ui-20261020](eval-ui-20261020/README.md) | Project D: Eval tab in the frontend, run shell and results/items views (2 PRDs). |
| [taxonomy-v1-20261020](taxonomy-v1-20261020/README.md) | Project A: `quantity_mismatch` concern, widened definitions, contract 1.2.0 (1 PRD). |
