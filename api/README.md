# onolys-api

Public `/v1` API + job worker (`onolys_api`). One image; `SERVICE_MODE=api|worker|combined`.

Local run: `uv run --package onolys-api uvicorn --factory onolys_api.app:create_app` (env: `.env.example`).

## OpenAPI (committed contract)
Regenerate (from repo root), then fail on drift:

    uv run --package onolys-api python -m onolys_api.openapi      # writes api/openapi.json
    git diff --exit-code api/openapi.json

`--out PATH` writes elsewhere; `--out -` prints to stdout. Output is deterministic (sorted keys, trailing newline).
