# Backend (`backend/`)

Verified commands (run from `backend/`):

- Install: `uv sync` (Python 3.12). Later runs can use `uv run --no-sync ...`.
- Tests (offline, no API key): `uv run --no-sync pytest -q`. Lint: `uv run --no-sync ruff check src tests` and `ruff format`.
- Tests that need an LLM use `StubClient` / `FixtureClient`; the `make_ctx` fixture in `tests/conftest.py` builds a `RequestContext`.

Check stage (`src/iaudit_backend/check/`): the verifier only observes; `synth.decide` owns the verdict table. Per-claim stall reasons are left in `ctx.extras["check_stalls"]` for the orchestrator (06). Log fields must be added to `ALLOWED_FIELDS` in `safe_log.py` or they are dropped.
