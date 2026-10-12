# Backend pre-release checklist

**Audience:** contributors.

1. `uv run pytest -q` and `uv run ruff check src tests eval` pass in `backend/`.
2. `uv run python -m eval.run --mode oracle --gate poc` passes.
3. One live run with the owner's key: `uv run python -m eval.smoke --base-url ...` against a server started with `IAUDIT_PIPELINE=full`, all 9 fixtures PASS. Note the estimated cost.
4. Refresh recordings if prompts changed: `uv run python -m eval.run --mode all --live --record`, then check that replay with `--strict-fresh` passes.
5. `docs/contracts/` is unchanged and `schema_version` is still `1.0.0`.
6. Sample the logs from a run: ids, counts and durations only, no transcript or assessment text.
7. `IAUDIT_CORS_ORIGINS` is set for the deployed UI origin.
8. Docs: `uv run pytest tests/test_docs_drift.py` passes.
