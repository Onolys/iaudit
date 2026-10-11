# Backend

HTTP service for the Interview Evidence Auditor. `POST /v1/audit` takes an assessment and an interview and returns a claim-by-claim evidence audit. It implements the [contract](../docs/contracts/README.md) (version 1.0.0).

Endpoint, errors, settings and warnings: [docs/reference/backend-api.md](../docs/reference/backend-api.md).

## Requirements

- Python 3.12
- [uv](https://docs.astral.sh/uv/)

## Setup

```bash
cd backend
uv sync
```

## Configure

Settings are `IAUDIT_*` environment variables (see the reference). For real audits, set a provider key that LiteLLM reads, for example `ANTHROPIC_API_KEY`. Tests and the stub modes need no key.

## Run

```bash
uv run uvicorn iaudit_backend.app:app --port 8000
curl http://localhost:8000/healthz
```

The health check returns `{"status":"ok"}`. Without a key, audits return 503.

## Test

```bash
uv run pytest -q
uv run ruff check src tests eval
```

Tests run offline.

## Smoke run

Runs the ADHD faithful fixture and its 8 variants through `POST /v1/audit`, prints PASS or FAIL for each, and exits 1 on any failure. A meaningful run needs a provider key.

```bash
uv run python -m eval.smoke
uv run python -m eval.smoke --base-url http://localhost:8000
```
