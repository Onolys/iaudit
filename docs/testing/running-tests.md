# Running the backend tests

**Audience:** contributors.

From `eaudit/`:

```bash
uv sync
uv run pytest -q
uv run ruff check src tests eval
```

The whole suite runs offline with no API key. Tests that need a model use `StubClient`, scripted clients or `FixtureClient`, and the `make_ctx` fixture in `tests/conftest.py` builds a request context. Recorded answers for replay are in `tests/fixtures/llm/` (a few) and `eval/recorded/` (the evaluation harness).

| Where | What |
|---|---|
| `tests/` | The service: API, assembler, prep, atomize, link, check, pipeline, logging. |
| `tests/pipeline/` | Orchestration with a scripted model for the worked example. |
| `tests/latency/` | Scaled-time latency and failure scenarios (a 60 s budget runs in about a second). |
| `eval/tests/` | Fixtures, gold labels, the scorer, the oracle, the harness CLI. |
| `tests/test_check_boundary_pairs.py` | Ten fictional boundary pairs for `quantity_mismatch` (scripted verifier output, exact concern set asserted). |

`tests/test_prompt_leakage.py` fails if any 8-word run of a few-shot example appears in the evaluation data. `tests/test_docs_drift.py` keeps the reference docs in step with the code.

The separate evaluation engine and its local API have their own offline suite: run `uv run pytest` and `uv run ruff check src tests` in the repository's `eval/` directory (see [evaluation.md](evaluation.md#dataset-evaluation-api-from-repository-eval)).
