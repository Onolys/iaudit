---
status: draft
summary: SP00 foundation, built first: test conventions (pytest markers unit/integration/live, vitest, no Playwright), a per-package ci.yml matrix that skips absent packages and stays green on main, per-PR preview deployments (no-traffic tagged revision pr-N of the staging API service in combined mode with fake adapters + Firebase Hosting channel pr-N + PR comment, cleaned up on close), and the 3-lane build plan.
date: 2026-11-20
---
# PRD: SP00 foundation — CI, testing, PR previews, build lanes

Repo/branch: Onolys/onolys (local `iaudit`) / `feat/miti-platform` · Depends on: CI tasks none; preview task needs SP06 staging minimal + SP04 runnable `SERVICE_MODE=combined` + SP05 `web/` buildable · Owns: `.github/workflows/ci.yml` (structure; job bodies per package), `.github/workflows/pr-preview.yml`, `.github/workflows/pr-preview-cleanup.yml`, `docs/reference/testing.md`

## TL;DR
Before feature work: one test convention, one CI that runs unit + integration tests per package on every push/PR (no Playwright, no live LLM/STT), and a preview deployment for every PR so the 3-person team can click through changes. Jobs for packages that do not exist yet are skipped, not failed, so the three lanes land in any order. Previews are one Cloud Run service per PR (api+worker in one process, fake adapters) plus a Firebase Hosting preview channel, in the staging project.

## Problem
CI today = job `eaudit` (uv, ruff, pytest in `eaudit/`) and `frontend` (npm typecheck + test) in `.github/workflows/ci.yml`, plus `nightly.yml` (`eval-oracle`). The platform adds `engines/{core,paudit,evaluation}`, `api/`, `web/`, `infra/`, built by three people at once. Without CI and conventions first, lanes diverge; without previews, reviewing web and API changes means reading diffs. r7 had cut previews; Tejit reversed that in r8 [RESOLVED: Tejit r8 (2026-11-20)].

## Goals / Non-Goals
**Goals:** CI + test conventions in place before any feature PR; green `main` at every step; fast per-package feedback (path filters); a clickable preview per PR; no spend on PRs (fake adapters, no LLM/STT); clear lane plan.
**Non-goals:** Playwright / browser E2E [RESOLVED: Tejit r8 (2026-11-20)]; hard coverage threshold; live tests in PR CI; `infra-plan.yml` / `tf-plan` SA / AR cleanup policy (stay deferred); deploy workflows (SP06); fork-PR previews; real-adapter previews until SP09.

## Requirements
**R1 Test conventions** [RESOLVED: r8 default (2026-11-20)]
- pytest per Python package: `engines/core`, `engines/eaudit`, `engines/paudit`, `engines/evaluation`, `api`. Markers registered in each `pyproject.toml`: `unit` (no network, no emulator), `integration` (fakes, in-process, Firestore emulator allowed), `live` (real LLM/STT; needs keys; never in PR CI; nightly or manual only). Default `addopts = -m "not live"`.
- Shared fixtures: `engines/core/src/onolys_core/testing/` (fake LLM/STT adapters, synthetic transcripts, `FakeRepo`), imported by other packages; package-local `tests/conftest.py` for the rest. Synthetic data only; no real audio or PHI in the repo.
- Firestore emulator for `api` integration tests (and rules tests); `FakeRepo` for unit tests (SP04 R12).
- Web: vitest (+ Testing Library + MSW) for `web/` (SP05 R9) and the existing `frontend/`; `tsc` typecheck. No Playwright, no axe in v1 [RESOLVED: Tejit r8 (2026-11-20)].
- Coverage reported (`pytest-cov`, vitest coverage) in the job summary; no threshold in v1. Lint: ruff (Python), tsc (TS).
- `docs/reference/testing.md`: how to run each suite locally, the markers, fixtures, how to add a package to CI.

**R2 CI matrix (`ci.yml`)** [RESOLVED: r8 default (2026-11-20)]
| Job | Runs | Notes |
|---|---|---|
| `eaudit` | ruff + pytest (`-m "not live"`) | working-directory `eaudit` until SP01 moves it to `engines/eaudit` (SP01 changes the path); job name kept for branch protection |
| `core`, `paudit`, `evaluation` | `uv sync --frozen` at the workspace root, ruff, `uv run --package <pkg> pytest` | skipped until `engines/<pkg>/pyproject.toml` exists |
| `api` | same + Firestore emulator (`firebase emulators:exec`) + `python -m onolys_api.openapi` diff against committed `api/openapi.json` | skipped until `api/` exists |
| `web` | `npm ci`, typecheck, lint, vitest, `build` | skipped until `web/package.json` exists |
| `frontend` | existing typecheck + test | name kept |
| `infra` | `terraform fmt -check -recursive`, `terraform init -backend=false`, `validate` | skipped until `infra/` exists; no credentials |
- Absent-package guard: a small `changes` job (`dorny/paths-filter` or `git diff` + `hashFiles`) outputs per-package flags; each job `if:` requires the package dir to exist AND (its paths or shared paths changed, or the event is `push` to `main`). A skipped job counts as success for branch protection. On `main` every existing package runs.
- Shared paths (root `pyproject.toml`, `uv.lock`, `engines/core/**`, workflow files) trigger all Python jobs.
- Concurrency per ref, `cancel-in-progress: true` (as today); permissions `contents: read`; 15 min timeouts. `nightly.yml` keeps `eval-oracle` and gains `live` checks later (SP01/SP09).
- Must stay green on `main` at every step: the CI task lands first and changes nothing about the existing two jobs except adding the guard.

**R3 PR preview (`pr-preview.yml`, `pr-preview-cleanup.yml`)**
Trigger: `pull_request` (opened, synchronize, reopened) from the same repo only; fork PRs skipped (no secrets). Concurrency `pr-preview-${{ github.event.number }}`, `cancel-in-progress: true`. Auth: WIF as `deployer-staging` (SP06 R13); no keys.
1. Build the platform image once (docker build, tag `pr-<N>-<sha>`), push to AR `onolys`.
2. Deploy a NO-TRAFFIC TAGGED REVISION (tag `pr-<N>`, revision `onolys-api-staging-pr-<N>-<sha7>-<run>-<attempt>`) of the existing staging API service `onolys-api-staging` (`gcloud run deploy --no-traffic --tag pr-<N>`), preview URL `https://pr-<N>---<staging api host>`: `SERVICE_MODE=combined` (api + worker in one process, in-memory queue, no Cloud Tasks), `ADAPTERS=fake` (stub pipeline, no LLM/STT spend), `FIRESTORE_DATABASE=staging`, staging Identity Platform, `GIT_SHA=<sha>`, `CORS_ORIGINS=<channel origin>`; CPU always allocated (so in-memory tasks finish after the response); scaling and the rest of the template are the staging service's (no per-preview max-instances). Only those keys are overridden; `deploy-staging.yml` re-specifies them (`SERVICE_MODE=api`, `ADAPTERS=real`, `CORS_ORIGINS`, `--cpu-throttling`) and moves 100% traffic to its own named revision, so nothing leaks into staging. Label `preview-real` on the PR switches to real adapters once SP09 lands.
3. Build `web/` (`VITE_FIRESTORE_DATABASE=staging`, staging `VITE_FIREBASE_*`); Hosting cannot rewrite to a Cloud Run tag, so the web build calls the tag URL directly (`VITE_API_BASE_URL=<tag url>/v1`); generate `firebase.json` at deploy time without the `/v1/**` rewrite and with the tag origin added to CSP `connect-src`; deploy to Hosting preview channel `pr-<N>` on site `onolys-app-staging`, expiry 7 days.
4. Post or update ONE PR comment (marker comment, edit in place) with the preview URL, sha and mode (fake/real).
- Cleanup (`pr-preview-cleanup.yml`, on `pull_request: closed`): remove tag `pr-<N>` from `onolys-api-staging`, delete that PR's revisions, delete channel `pr-<N>`; ignore not-found.
- IAM (SP06 grants, see its R13): no new Cloud Run grant: `deployer-staging` already has `run.developer` on the staging services and `serviceAccountUser` on `api-staging` (SP06 R13); Firebase Hosting admin for channels.
- Sign-in on previews: staging Identity Platform authorised domains must allow the channel hosts (`onolys-app-staging--pr-*.web.app`): Terraform item in SP06 or a manual step.
- Preview data lands in the `staging` Firestore DB under real staging accounts; no real PHI is ever used there.

**R4 Lane plan (3 people)**
| Lane | Order |
|---|---|
| A engine | SP01 → SP02 → SP03 |
| B platform | SP06 (staging minimal) → SP04 → SP09 |
| C web/foundation | SP00 CI tasks first → SP05 web on MSW mocks (does not wait for SP04) → SP00 preview task once SP06 staging minimal + SP04 skeleton exist → SP08 landing |
Sync points: SP01 workspace PR lands first (SP04 needs its types; CI eaudit path changes); SP03 report schema → SP05 types; SP04 `api/openapi.json` → SP05 generated client; SP06 staging minimal + SP04 combined mode + SP05 buildable → preview; SP09 needs SP02, SP03, SP04, SP06.

## Architecture
```
PR push ─► ci.yml: changes ─► [eaudit|core|paudit|evaluation|api|web|frontend|infra] (skip if absent/unchanged)
PR push ─► pr-preview.yml ─WIF─► AR image ─► tagged revision pr-N of onolys-api-staging (no traffic, combined, fake, DB staging)
                              └► web build ─► Hosting channel pr-N (onolys-app-staging)  web calls https://pr-N---<api host>/v1
PR close ─► pr-preview-cleanup.yml ─► delete service + channel
```

## Decisions
| # | Decision | Choice | Alternatives | Why |
|---|---|---|---|---|
| D1 | Browser E2E | None in v1 (Tejit r8) | Playwright | Vitest/MSW flows + manual preview check suffice |
| D2 | Live tests | Never in PR CI; `live` marker; nightly/manual (r8 default) | Run on PRs | Cost, flakiness, secrets |
| D3 | Missing packages | Job skipped via guard (r8 default) | Fail; stub jobs | Lanes land in any order; main stays green |
| D4 | Preview shape | One combined-mode no-traffic tagged revision (`pr-<N>`) of the staging API service + Hosting channel (owner, 2026-11-21; supersedes r8 separate `onolys-pr-<N>` service) | Separate service per PR; two services + Cloud Tasks; shared staging | Owner chose tagged revision on 2026-11-21 because Cloud Run lacks `resource.name` IAM conditions, so a `onolys-pr-*`-scoped grant is impossible and an unconditional one would let the staging deployer touch prod; a tagged revision needs only the existing `run.developer` on staging services |
| D5 | Preview adapters | Fake by default; `preview-real` label opts in after SP09 (r8 default) | Always real | No LLM/STT spend on every push |
| D6 | Preview data | Staging Firestore DB, shared (r8 default) | DB per PR | Simpler; PHI-free |
| D7 | Fork PRs | No preview | Pull-request-target | No secrets exposure |
| D8 | Coverage | Report only (r8 default) | Threshold | Too early to set one |
| D9 | Lanes | 3 (Tejit r8) | Max 2 sub-projects | Team size |

## Manual steps
1. Tejit: staging Identity Platform authorised domains for preview channel hosts, if SP06 Terraform cannot manage them.
2. Tejit: GitHub repo variables for the preview workflow come from SP06 Terraform outputs (same as deploy-staging).
3. Optional: branch protection with required `eaudit` and `frontend` (SP01 note) plus new job names once packages exist.

## Risks / Open Questions
- [OPEN until measured] Whether Identity Platform accepts a wildcard authorised domain; fallback: add each channel host in the preview workflow via the Identity Toolkit API (needs one more deployer role) or sign in on previews with email links only.
- [OPEN until measured] Combined-mode in-memory tasks finishing on min-0/max-1 with CPU always allocated; fallback: `min-instances 1` while the PR is open.
- Risk: preview leftovers if cleanup fails; mitigated by 7-day channel expiry and the `pr-<N>` tag / `onolys-api-staging-pr-<N>-*` revision naming so a sweep is trivial.
- Risk: concurrent previews share the staging DB; accepted (D6).
- Risk: preview depends on SP04/05/06; CI-only tasks are not blocked by it.
- [DEFERRED: After launch] `infra-plan.yml`, `tf-plan` SA, AR cleanup policy, Playwright + axe, coverage threshold.

## Acceptance Criteria
1. `ci.yml` is green on `main` and on a PR when only some packages exist; absent packages show as skipped, not failed; `eaudit` and `frontend` job names unchanged.
2. Each existing Python package runs `pytest -m "not live"`; a deliberately failing unit test in any package fails its job; no job needs LLM/STT keys; no live test runs in PR CI.
3. `docs/reference/testing.md` documents markers, fixtures, local commands and how to add a package.
4. A sample PR gets one PR comment with a working preview URL; sign-up/in and the stub flow work through `/v1` on the channel; a new push updates the same comment.
5. Closing the PR removes tag `pr-<N>`, deletes that PR's revisions and channel `pr-<N>`.
6. A fork PR runs CI but no preview.
