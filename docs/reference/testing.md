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

### Flaky tests (web)

Mark a known-flaky test by moving it to a `*.flaky.test.ts(x)` file next to its suite and giving it `{ retry: 2 }`. The default `npm test` excludes these files (blocking); `npm run test:flaky` runs only them, in a `continue-on-error` CI step (visible, non-blocking). Every flaky test needs a follow-up issue to fix the root cause, then move it back into the normal suite.

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
| Only some packages exist: green, with skipped jobs | Pass (real run) | Mechanism: `scripts/ci/changes.sh` sets a package flag only if its marker exists and its paths (or shared paths) changed; each job has `if: needs.changes.outputs.<pkg> == 'true'`, so an untouched or absent package gives a skipped job (counts as passing). Offline proof: `scripts/ci/test_changes.sh`. Real run: scratch draft PR #36 (closed, not merged; base `feat/miti-platform`, one comment line in `engines/evaluation/src/onolys_evaluation/tone.py`), CI run 44834423699, conclusion `success`. Ran: `changes`, `evaluation` (both success). Skipped: `frontend`, `api`, `paudit`, `eaudit`, `admin-backend`, `admin-auth`, `core`, `web`, `infra`. Proven 2026-11-20. |
| Fork PR runs CI but not the preview | Pass (real run) | Scratch draft fork PR #38 (fork of Onolys/onolys, closed, not merged; base `feat/miti-platform`, one comment line in `web/src/lib/codepoints.ts`). CI run 44845016353 `success` (no first-time-contributor approval needed). `pr-preview` run 44845016351 and `pr-preview-cleanup` run 44845144197: `skipped` (same-repo guard); no PR comment; no `pr-38` tag, revision or channel created. Proven 2026-11-21. Owner action: the fork `tejitpabari99/onolys-forkproof` could not be deleted (gh token lacks `delete_repo` scope); delete it in GitHub UI. |
| Preview cleanup on PR close | Pass (real run, after fix dec7ac9) | Re-proof on scratch draft same-repo PR #39 (closed, not merged, branch deleted). Preview run 44847971513 `success`: tag `pr-39`, revision `onolys-api-staging-pr-39-5a9f6f9-8-1`, channel `pr-39`. Cleanup run 44848167122 `success`: tag and channel `pr-39` gone; revision was the latest created, so logged `left for sweep: onolys-api-staging-pr-39-5a9f6f9-8-1` (kept by design; deleted on the next staging API deploy by `sweep-previews`). Re-run of the same cleanup run (attempt 2) `success`: `left for sweep` again, channel `already gone (ignored)`, sweep kept the latest and tagged `pr-35` revisions (idempotent). Sweep proven live: staging deploy run 44847620450 (push of b1b0ac3) job `sweep-previews` `success` and removed the orphan `onolys-api-staging-pr-37-a7b1dea-5-1` left by #37; scratch channel `pr-37` deleted by hand. Earlier FAIL (run 44844909790 on PR #37: `latest created Revision ... cannot be directly deleted` aborted before the channel delete) fixed in dec7ac9. Proven 2026-11-21. |

Branch protection (require `CI` checks on `main`) is an owner step.

## Preview auth domains

Staging PR previews (Hosting channels on `onolys-app-staging`) need their host in the Identity Platform authorised domains, or sign-in fails there. Checked live 2026-11-20 (SP06 task 6): the wildcard `onolys-app-staging--pr-*.web.app` is **rejected** by the API (`400 INVALID_AUTHORIZED_DOMAIN : ... should only contain the valid domain`). So the preview workflow must add each channel host after `firebase hosting:channel:deploy` reports it:

```
python3 infra/scripts/identity-config.py --domains-only --add-domain <channel-host>
```

- Auth: ADC for project `onolys` (the staging deployer SA needs Identity Platform admin: `roles/firebaseauth.admin`).
- Idempotent and add-only (union with the live list; it never removes). Terraform ignores `authorized_domains` drift, so added hosts are not pruned on apply.
- Hosts accumulate (limit 1000); prune closed-PR hosts occasionally by PATCHing `authorizedDomains` on `https://identitytoolkit.googleapis.com/admin/v2/projects/onolys/config`.

## Preview acceptance (SP00 task 9), measured 2026-11-21

PR #35 preview: web `onolys-app-staging--pr-35-kkj34ogl.web.app`, API tag `pr-35` (revision `onolys-api-staging-pr-35-095861a-4-1`, `SERVICE_MODE=combined`, `ADAPTERS=stub`, staging Firestore).

| Check | Result | Evidence |
|---|---|---|
| Authorised domains, wildcard | Rejected (see above); not tried again | Live `authorizedDomains` (Identity Toolkit admin v2): `localhost, onolys.firebaseapp.com, onolys.web.app, app.onolys.com, onolys-app.web.app, onolys-app-staging.web.app, onolys-admin-staging.web.app`. No `pr-35` host. |
| Email/password sign-in on the preview host | Pass | Playwright: `/login`, submit, redirect to `/` in 3.2 s, sessions list loads from the combined API. Email/password does not use the authorised-domain list. |
| Google popup sign-in on the preview host | FAIL | Clicking "Continue with Google" opens no popup; the form shows "Something went wrong. Please try again." On staging (`onolys-app-staging.web.app`) the popup opens `onolys.firebaseapp.com/__/auth/handler`. Cause: host not in authorised domains. Screenshots: `pv-google.png`, `st-google.png` (scratchpad of the 2026-11-21 session). |
| Workflow adds the channel host | Not wired | `.github`, `scripts/ci` have no call to `identity-config.py --add-domain`; the deployer SA role `roles/firebaseauth.admin` is also not confirmed. Fix needs a workflow change plus an IAM change in SP06 Terraform (owner approval, not applied). |
| Combined mode, min 0 / max 1, CPU always allocated (task finishes after the HTTP response) | Pass | Waited until Cloud Monitoring showed 0 instances for the revision (about 17 min idle), then a cold run with a synthetic 20 s tone and stub adapters: create 202 at 4.7 s, PUT 200 at 7.1 s, complete 202 at 7.7 s, `complete` to `awaiting_input` 18.1 s (cold start included), confirm to `report_ready` 1.8 s, report GET 200, session DELETE 204. Background work completed on the single instance. |
| Test data | Cleaned | The two sessions of the test account on the preview (the staging Firestore is shared with staging) were deleted via the API (204 each); list is empty. |

Owner/infra action: Google sign-in on previews needs each channel host added to the authorised domains (workflow step plus `roles/firebaseauth.admin` for the preview deployer), or accept email/password only on previews. Acceptance criterion 4 (preview sign-in) is met for email/password only.

Owner decision 2026-11-21: Google sign-in on previews is not needed. The owner uses email/password on previews, so there is no authorised-domain automation (no workflow step, no `roles/firebaseauth.admin` for the preview deployer). The FAIL above is accepted as won't-fix.
