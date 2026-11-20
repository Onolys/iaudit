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
