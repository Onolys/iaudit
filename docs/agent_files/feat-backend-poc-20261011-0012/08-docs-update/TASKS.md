---
status: approved
summary: Four core docs tasks (backend README, backend-api reference, architecture blurb with links and the approved mission wording, link check); one gated optional row.
date: 2026-10-11
---
# Tasks: 08 Docs update (core)

Source of truth: [PRD.md](PRD.md). Documents the landed backend, last. Docs describe what the code does, verified against the tree (resolved O-4); unmeasured numbers say "not yet measured" (O-3 deferred).

| # | Task | Depends on | Status |
|---|---|---|---|
| 1 | `backend/README.md` quickstart including the smoke run | 06, 07a | todo |
| 2 | `docs/reference/backend-api.md` | 06 | todo |
| 3 | Architecture blurb, index links, mission check 7 wording | 2 | todo |
| 4 | Link check and no-transcript-text check | 1, 3 | todo |
| 5 | [OPTIONAL, gated] Optional docs | all core in every SP | todo |

## Task 1 — Backend README
What it is / what it means: How to run the backend (R10 core, D1).
What changes at a high level: Under 60 lines: what it is, Python 3.12 and uv, `uv sync`, key env vars (`ANTHROPIC_API_KEY` by name only) with a link to `backend-api.md`, run, `/healthz`, tests, and `uv run python -m eval.smoke`.
Done when: every command in it runs as written.

## Task 2 — API reference
What it is / what it means: Lookup facts for users (R3 core, D4, D6).
What changes at a high level: `backend-api.md` covering both endpoints, request check order, the error table (including 503 when nothing completes and 504 on deadline, resolved O-2), a compact `IAUDIT_*` table read from `Settings`, limits, and when each warning is emitted.
Done when: every row traces to code.

## Task 3 — Architecture, links, mission wording
What it is / what it means: Wire the docs together and apply the approved wording (R2, R10, D5).
What changes at a high level: A short backend section in `docs/architecture.md` linking to `backend-api.md`; Backend and Contract links in the root `README.md`; one index line in `docs/reference/README.md`; mission check 7 in `docs/mission.md` becomes "exaggerates or understates" (resolved O-1, wording only, contract stays 1.0.0). No back-link from frontend docs (resolved O-5).
Done when: the links resolve and the contract files are unchanged.

## Task 4 — Checks
What it is / what it means: Docs stay correct and PHI-free (acceptance 3, 4, 7).
What changes at a high level: Check every relative link in the changed docs and grep that no fixture transcript text appears in docs.
Done when: both checks pass.

## Task 5 — [OPTIONAL, gated] Optional docs
What it is / what it means: The PRD's Optional tier, started only after all core work in every sub-project is done.
What changes at a high level: ADRs, concepts, implementation and testing docs, examples, `configuration.md`, `warnings.md`, contracts README sentence, drift test.
Done when: each optional acceptance part passes.
