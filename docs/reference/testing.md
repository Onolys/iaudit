# Testing

How to write and run tests in every package. One convention for all.

**Audience:** contributors.

Package paths below are `engines/eaudit/`; the other Python packages (`engines/core`, `engines/paudit`, `engines/evaluation`, `api`) follow the same layout.

## Markers (Python, pytest)

| Marker | Meaning | Runs by default | In PR CI |
|---|---|---|---|
| `unit` | No network, no emulator | yes | yes |
| `integration` | Fakes, in-process; Firestore emulator allowed | yes | yes |
| `live` | Real LLM/STT; needs keys | no | never (nightly or manual) |

Every package's `pyproject.toml` carries this block. Copy it when you create a package:

```toml
[tool.pytest.ini_options]
addopts = "-m 'not live'"
markers = [
  "unit: no network, no emulator",
  "integration: fakes, in-process; Firestore emulator allowed",
  "live: real LLM/STT, needs keys; excluded by default, never in PR CI",
]
```

Mark new tests with `@pytest.mark.unit`, `@pytest.mark.integration` or `@pytest.mark.live`. Unmarked tests still run (existing `eaudit` tests are unmarked); mark new ones. `engines/eaudit/tests/test_markers.py` is the sample of each kind.

Select with `-m`. `-m` on the command line overrides the default `addopts` value, so `-m live` runs only live tests.

## Fixtures

- Shared: `engines/core/src/onolys_core/testing/` (fake LLM/STT adapters, synthetic transcripts, `FakeRepo`). Owned by SP01; other packages import it.
- Package-local: `tests/conftest.py`.
- Synthetic data only. No real audio or PHI in the repo.

## Local commands

Python (from the package directory; first run `uv sync`):

```bash
cd engines/eaudit
uv run --no-sync ruff check src tests                 # lint
uv run --no-sync pytest -q                            # default: everything except live
uv run --no-sync pytest -q -m unit                    # only unit
uv run --no-sync pytest -q -m "unit or integration"   # explicit non-live
uv run --no-sync pytest -q -m live                    # live only; needs keys
```

Web (`frontend/`, later `web/`): vitest, Testing Library, MSW. No Playwright, no browser E2E, no axe in v1.

```bash
cd frontend
npm ci
npm run typecheck   # tsc
npm test            # vitest run
```

## Firestore emulator

Used by `api` integration tests and Firestore rules tests. Unit tests use `FakeRepo` instead. Run a suite under the emulator with:

```bash
firebase emulators:exec --only firestore "uv run --no-sync pytest -q -m integration"
```

The `api/` package does not exist yet; this command applies once it does.

## Coverage (report only)

No threshold in v1. Python uses `pytest-cov` (a dev dependency):

```bash
cd engines/eaudit
uv run --no-sync pytest -q --cov=eaudit --cov-report=term-missing
```

Web: add `@vitest/coverage-v8` to the package's dev dependencies, then `npx vitest run --coverage`. (Not yet installed in `frontend/`.)

## Add a package to CI

1. Create the package with the marker block above and `pytest`, `pytest-cov`, `ruff` in its dev group. Commit its lockfile.
2. Add a job to `.github/workflows/ci.yml`, modeled on the `eaudit` job: `uv sync --frozen --package <name>` from the repo root, `ruff check`, `pytest -q` (live is excluded by the default `addopts`). Web packages follow the `frontend` job (`npm ci`, `npm run typecheck`, `npm test`).
3. Keep the job skipped while the package directory is absent, so main stays green.
4. Never run `live` tests in PR CI.

## CI behaviour record

Evidence for the foundation CI guarantees. Observed from real PR runs (`gh run view -R Onolys/onolys`, PR #35, branch `feat/miti-platform`), not scratch PRs. Recorded 2026-11-20.

| Scenario | Result | Evidence |
|---|---|---|
| A failing check in one package fails only its job | Pass | Run 44817430417 (sha 35fa3b0): `core` failed at `ruff check` (its pytest step skipped); `api`, `eaudit`, `paudit`, `evaluation`, `admin-auth`, `admin-backend`, `frontend`, `web`, `infra` all succeeded. Run 44809066444 (746a61b): only `web` failed, the other 10 jobs green. Run 44823615891 (5ee3d02): `api` and `eaudit` failed (a docs-drift test in `eaudit`), the rest green. Each failure is confined to the package that owns it. |
| Live tests never run in PR CI | Pass | PR jobs pass `-m "not live"` (`core`, `api`, `paudit`, `evaluation`); package `addopts` also exclude it. Run 44826772322 `api` log: `collected 823 items / 1 deselected / 822 selected`, `822 passed, 1 deselected`. Run 44823615891 `eaudit` log: `1 failed, 1381 passed, 1 deselected`. The only job that runs `-m live` is `api-real-mode` in `nightly.yml` (schedule/dispatch only). |
| No PR job reads LLM/STT keys | Pass, now enforced | `scripts/ci/check_no_llm_keys_in_pr_workflows.py` runs in the `changes` job of `ci.yml`. It fails on any provider key name (`ANTHROPIC_API_KEY`, `GEMINI_API_KEY`, `OPENAI_API_KEY`, `LITELLM_*`, `DEEPGRAM_*`, `STT_*` and similar, or a `secrets.*` with such a name) in a workflow triggered by `pull_request`/`pull_request_target`, including local reusable workflows they call. Today the only reference is in `nightly.yml`, which is not PR-triggered. Tests: `scripts/ci/test_check_no_llm_keys_in_pr_workflows.py` (passes on the repo, fails on the planted fixtures in `scripts/ci/key_guard_fixtures/bad`). `ci.yml` also runs the guard on that planted fixture and fails if the guard does not fail. |
| Only some packages exist: green, with skipped jobs | Pending real-run proof | Mechanism: `scripts/ci/changes.sh` sets a package flag only if its marker (`pyproject.toml`, `package.json` or the directory) exists, and each job has `if: needs.changes.outputs.<pkg> == 'true'`, so an absent package gives a skipped job (counts as passing). Proven offline by `scripts/ci/test_changes.sh` (absent `web`, `infra`, `evaluation`, `paudit` stay false until created). Not yet seen in a real run: PR #35 edits `.github/workflows/` and `scripts/ci/`, which are CI-shared paths, so every existing package runs; the all-jobs-skipped runs on this branch (e.g. 44801478016) came from a failed `changes` job, not path filtering. Needs: a PR that touches only one package path (or a branch where a package directory is absent) and shows the other jobs as `skipped`. |
| Fork PR runs CI but not the preview | Pending (task 7) | `ci.yml` uses `pull_request` with read-only permissions and no secrets, so fork PRs run it. `pr-preview.yml` does not exist yet (SP00 task 7). Needs: that workflow with a same-repo guard, then a fork PR showing CI green and no preview comment/deploy. |

Branch protection (require `CI` checks on `main`) is an owner step.

## Preview auth domains

Staging PR previews (Hosting channels on `onolys-app-staging`) need their host in the Identity Platform authorised domains, or sign-in fails there. Checked live 2026-11-20 (SP06 task 6): the wildcard `onolys-app-staging--pr-*.web.app` is **rejected** by the API (`400 INVALID_AUTHORIZED_DOMAIN : ... should only contain the valid domain`). So the preview workflow must add each channel host after `firebase hosting:channel:deploy` reports it:

```
python3 infra/scripts/identity-config.py --domains-only --add-domain <channel-host>
```

- Auth: ADC for project `onolys` (the staging deployer SA needs Identity Platform admin: `roles/firebaseauth.admin`).
- Idempotent and add-only (union with the live list; it never removes). Terraform ignores `authorized_domains` drift, so added hosts are not pruned on apply.
- Hosts accumulate (limit 1000); prune closed-PR hosts occasionally by PATCHing `authorizedDomains` on `https://identitytoolkit.googleapis.com/admin/v2/projects/onolys/config`.
