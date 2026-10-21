# Backend

HTTP service for the Interview Evidence Auditor. `POST /v1/audit` takes an assessment and an interview and returns a claim-by-claim evidence audit (with `full`, plus `run_info`: model ids and prompt hashes). It implements the [contract](../docs/contracts/README.md) (version 1.1.0).

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

To try an audit without a key, start the stub pipeline and post the contract example. It returns 200 with an empty valid audit (`IAUDIT_LLM_MODE=stub` returns 503 instead):

```bash
IAUDIT_PIPELINE=stub uv run uvicorn iaudit_backend.app:app --port 8000
curl -s -X POST http://localhost:8000/v1/audit -H 'content-type: application/json' \
  -d @../docs/contracts/examples/request.json
```

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

More evaluation modes (gold, linked, e2e, replay): [eval/README.md](eval/README.md).
