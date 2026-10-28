# scripts/

| File | Purpose |
|---|---|
| `dev.sh` | Start backend, eval server and Vite together with matching ports and env. |

## dev.sh

```
scripts/dev.sh [--check] [--stub]
```

Starts, each in its own process group with prefixed output:

| Prefix | Process | Port |
|---|---|---|
| `[backend]` | `uv run uvicorn eaudit.app:app` (in `eaudit/`) | 8000 |
| `[eval]` | `uv run uvicorn iaudit_eval.server.app:app --no-access-log --host 127.0.0.1` (in `eval/`) | 8100 |
| `[web]` | `npm run dev` (in `frontend/`) | 5173 |

Env set by the script: `IAUDIT_BACKEND_URL=http://127.0.0.1:8000` (eval),
`VITE_AUDIT_URL=http://localhost:8000/v1/audit`, `VITE_MOCK=false`,
`IAUDIT_EVAL_PORT=8100` (web).

Flags:

- `--check`: preflight only (`uv`, `node`/`npm`, `frontend/node_modules`, free ports; names the port holder), then exit.
- `--stub`: sets `IAUDIT_PIPELINE=stub` for the backend.

Provider keys (`ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `LITELLM_API_KEY`) are checked for presence only; a warning is printed if none is set. Values are never printed.

After start it waits up to 30 s for backend `/healthz` and eval `/health`, then prints URLs. Ctrl-C (or any child exiting) stops all children (TERM, then KILL after 5 s); a child exit makes the script exit non-zero.

First time: `cd frontend && npm ci`.

The first live smoke of the full script (all three up, Ctrl-C leaves no orphans, `--stub`) is an owner manual check. Agents run only `bash -n` and `--check`.

Ports are fixed by this script; exporting `IAUDIT_EVAL_PORT` does not change its eval
listen port. Eval access logs are disabled so raw item paths/query text are not logged.
See the [eval API reference](../docs/reference/eval-api.md) for independent-server
configuration. Real dataset downloads and live audits are owner-only checks.
`--check` starts no services and is not a full-stack smoke test.
