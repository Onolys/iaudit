---
status: draft
summary: SP00 tasks: pytest/vitest conventions, guarded per-package ci.yml (skips absent packages), then per-PR preview deploy + cleanup, testing.md.
date: 2026-11-20
---
# Tasks: SP00 foundation — CI, testing, PR previews
Source of truth: 00-foundation/PRD.md. Tasks 1-6 are CI/test work with no dependency on other sub-projects (jobs skip until packages exist). Tasks 7-9 are the PR preview and need SP06/SP04/SP05 pieces.

| # | Task | Depends on | Status |
|---|---|---|---|
| 1 | Test conventions + `testing.md` | — | done |
| 2 | `ci.yml` absent-package guard on existing jobs | — | done |
| 3 | Python package jobs: core, paudit, evaluation | 2 | done |
| 4 | `api` job (emulator + OpenAPI diff) | 2, 3 | done |
| 5 | `web` and `infra` jobs | 2 | done |
| 6 | CI behaviour proof (skip, fail, live-excluded, fork) | 2, 3, 4, 5 | in-progress |
| 7 | `pr-preview.yml`: build, deploy, comment | 6, SP06 T9, SP04 T1, SP05 T1 | todo |
| 8 | `pr-preview-cleanup.yml` | 7 | todo |
| 9 | Preview acceptance + build-time measurements | 7, 8 | todo |

Parallel lanes: all of 1-6 belong to Lane C (web/foundation), the first thing built; 1 and 2 can run at the same time (different files), then 3, 4, 5 can run in parallel with each other (same workflow file, so merge carefully; 3 and 5 are independent of 4). Lanes A (engine) and B (platform) should not start feature PRs until task 2 is green on main, and their packages then light up their own jobs automatically. 7-9 are Lane C, after SP05 is buildable and Lane B has staging minimal and combined mode.

## Task 1 — Test conventions and testing.md
What it is / what it means: one shared way to write and run tests across all packages (PRD R1, D1, D2, D8). Python: `unit`, `integration`, `live` markers; web: vitest, no Playwright.
What changes at a high level: add the marker registration and default `-m "not live"` to the existing `eaudit/` pytest config (other packages copy the same block when they are created); write `docs/reference/testing.md` covering markers, shared-fixture location (`engines/core/.../testing/`, owned by SP01), local commands per suite, emulator use, coverage reporting, and how to add a package to CI. Coverage via `pytest-cov` and vitest coverage, report-only.
Done when: `eaudit` tests run with the markers registered (no unknown-marker warnings) and `live` excluded by default; a marked sample test of each kind proves selection works; `testing.md` exists and its commands were run once; the existing `eaudit` CI job passes.

## Task 2 — ci.yml absent-package guard
What it is / what it means: the base of the matrix (PRD R2, D3). Lanes land in any order and main stays green.
What changes at a high level: add a `changes` job outputting per-package flags (paths-filter or git diff plus directory-exists check). Every job gets an `if:` requiring the package dir to exist and (its paths or shared paths changed, or push to main). Shared paths: root `pyproject.toml`, `uv.lock`, `engines/core/**`, workflow files. Existing `eaudit` and `frontend` jobs keep their names and bodies; add per-ref concurrency, read-only permissions and 15-min timeouts where missing.
Done when: on a PR touching only `frontend/`, `eaudit` is skipped and `frontend` runs; on push to main everything existing runs; job names unchanged; a skipped job shows green for protection. Proven by running the workflow on a branch (CI itself is the test).

## Task 3 — Python package jobs (core, paudit, evaluation)
What it is / what it means: jobs that start working the moment SP01-SP03 create their packages (PRD R2).
What changes at a high level: three jobs, each `uv sync --frozen` at the workspace root, ruff, `uv run --package <pkg> pytest` with `-m "not live"` and coverage in the job summary; skipped until `engines/<pkg>/pyproject.toml` exists. Make the `eaudit` job path-switchable so SP01 only changes the working directory. No LLM/STT keys anywhere.
Done when: with no `engines/` directory all three jobs show skipped on a PR; a throwaway branch adding a minimal `engines/core` package with one passing and one deliberately failing unit test shows the job running and failing as expected (then removed). Runs in `ci.yml`.

## Task 4 — api job
What it is / what it means: CI for the platform API once `api/` exists (PRD R2, R1 Firestore emulator).
What changes at a high level: job runs uv sync, ruff, pytest under `firebase emulators:exec` (Firestore emulator, also used for rules tests), then regenerates the OpenAPI document via the module command and fails on a diff against committed `api/openapi.json`. Skipped until `api/` exists. Emulator tooling cached to keep the job inside 15 minutes.
Done when: skipped cleanly with no `api/`; a throwaway minimal `api/` with an integration test reading/writing Firestore passes in the emulator, and a changed route without regenerating `openapi.json` fails the job. Runs in `ci.yml`.

## Task 5 — web and infra jobs
What it is / what it means: front-end and Terraform checks, credential-free (PRD R2).
What changes at a high level: `web` job: `npm ci`, typecheck, lint, vitest (+ coverage summary), `build`; skipped until `web/package.json` exists. `infra` job: `terraform fmt -check -recursive`, `terraform init -backend=false`, `validate`; skipped until `infra/` exists. No Playwright, no axe. Existing `frontend` job unchanged.
Done when: both skip with no `web/` or `infra/`; throwaway minimal `web/` (one vitest test, one build) and `infra/` (one valid file; one badly formatted file must fail) behave correctly, then are removed. Runs in `ci.yml`.

## Task 6 — CI behaviour proof
What it is / what it means: the checks from acceptance criteria 1, 2 and 6 held together as a recorded result, so the team can trust a green main.
What changes at a high level: run the scenarios on a scratch PR and record outcomes in `testing.md`: only-some-packages-exist stays green with skipped jobs; a deliberately failing unit test in a package fails only its job; no job reads LLM/STT keys; no `live` test runs; a fork PR runs CI but not the preview (confirmed once task 7 exists). Add a small guard test or workflow check that fails if a PR-triggered workflow references secret LLM/STT env names.
Done when: scenarios pass and are written up; the key-guard check runs in `ci.yml` and fails on a planted reference. Branch protection note kept as an owner step.

## Task 7 — pr-preview.yml: build, deploy, comment
What it is / what it means: one clickable preview per same-repo PR (PRD R3, D4-D7). Needs SP06 staging minimal (`deployer-staging` WIF, AR `onolys`, site `onolys-app-staging`), SP04 combined mode with fake adapters, and a buildable SP05 `web/`.
What changes at a high level: workflow on opened/synchronize/reopened, same-repo only, concurrency per PR number. Build and push the image tagged `pr-<N>-<sha>`; deploy Cloud Run `onolys-pr-<N>` (combined mode, `ADAPTERS=fake`, staging DB, `GIT_SHA`, max 1 instance, min 0, CPU always allocated); build `web/` with staging settings; generate `firebase.json` rewriting `/v1/**` to the service before SPA fallback; deploy channel `pr-<N>` with 7-day expiry; create or update one marker PR comment (URL, sha, mode). `preview-real` label wired but inert until SP09.
Done when: a sample PR gets exactly one comment, with a working URL; a second push updates the same comment; sign-up/sign-in and the stub flow work through `/v1`; a fork PR gets no preview. Workflow lint (actionlint) runs in `ci.yml`.

## Task 8 — pr-preview-cleanup.yml
What it is / what it means: no preview leftovers (PRD R3, risk on cleanup).
What changes at a high level: on `pull_request: closed`, delete service `onolys-pr-<N>` and channel `pr-<N>`, ignoring not-found; same WIF identity.
Done when: closing the sample PR removes both resources (verified by listing them); rerunning on an already-clean PR succeeds; actionlint passes in `ci.yml`.

## Task 9 — Preview acceptance and measurements
What it is / what it means: settle the two "[OPEN until measured]" items from the PRD and tick acceptance criteria 4 and 5.
What changes at a high level: (a) Identity Platform wildcard authorised domain for `onolys-app-staging--pr-*.web.app`: measure whether it is accepted. Fallback if not: add each channel host from the workflow via the Identity Toolkit API (one extra deployer role in SP06), or email-link sign-in only on previews. (b) In-memory combined-mode tasks finishing at min 0 / max 1 with CPU always allocated: measure with a stub run. Fallback if tasks stall: `min-instances 1` while the PR is open (cleanup deletes it). Record both results and the chosen fallback in `testing.md`.
Done when: both measurements recorded with outcome and, if failed, the fallback applied and re-tested; acceptance criteria 4 and 5 verified end to end on a sample PR.

## Owner steps
Owner-only (Tejit), from the PRD Manual steps:
1. Add staging preview channel hosts to Identity Platform authorised domains if SP06 Terraform cannot manage them (task 9 shows which).
2. Set GitHub repo variables for the preview workflow from SP06 Terraform outputs (same as deploy-staging).
3. Optional: branch protection with required `eaudit` and `frontend`, plus new job names once the packages exist.
