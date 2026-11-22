# Local setup and live verification

Set up every component, run the offline checks, and work through the owner live checks after taxonomy v1 (contract 0.0.1).

**Audience:** contributors and the repository owner.

## Prerequisites

- [uv](https://docs.astral.sh/uv/) and Python 3.12 (`requires-python = ">=3.12,<3.13"` in `engines/eaudit/` and `eval/`).
- Node and npm. CI uses Node 22; the repo pins no other version.
- For live runs, a provider key that LiteLLM reads. `scripts/dev.sh` checks `GEMINI_API_KEY`, `ANTHROPIC_API_KEY`, `OPENAI_API_KEY` and `LITELLM_API_KEY` for presence; the default models are Google Gemini (`GEMINI_API_KEY`) ([configuration](../reference/configuration.md)). Offline tests and stub modes need no key.

## One-time setup

```bash
(cd engines/eaudit && uv sync)
(cd eval && uv sync)
(cd frontend && npm ci)
```

Frontend env: `cp frontend/.env.example frontend/.env.local` (only for running Vite by hand; `scripts/dev.sh` sets its own). See [frontend README](../../frontend/README.md).

Eval datasets: the ADHD fixtures ship in `engines/eaudit/eval/`; no download. TofuEval needs a download (licensed text, stored under `eval/data/`, gitignored): in the Eval tab pick TofuEval and click **Download data**, or `POST /datasets/tofueval/download` ([eval API](../reference/eval-api.md), [eval UI](../reference/eval-ui.md#start-download-watch-and-abort)). Confirm the status is `ready` and inspect the hashes in `eval/data/tofueval/download.json` ([eval README](../../eval/README.md#manual-owner-steps)).

## Run everything

```bash
scripts/dev.sh --check   # preflight only: uv, node/npm, node_modules, free ports
scripts/dev.sh           # backend, eval server, Vite
scripts/dev.sh --stub    # same, IAUDIT_PIPELINE=stub (no key, empty valid audits)
```

| Service | URL |
|---|---|
| Backend | `http://127.0.0.1:8000` (`/healthz`) |
| Eval server | `http://127.0.0.1:8100` (`/health`) |
| Web (eaudit and Eval tabs) | `http://localhost:5173` |

Ports are fixed by the script. Ctrl-C stops all three. Details: [scripts/README.md](../../scripts/README.md).

Components alone:

```bash
(cd engines/eaudit && uv run uvicorn eaudit.app:app --port 8000)
(cd engines/eaudit && IAUDIT_PIPELINE=stub uv run uvicorn eaudit.app:app --port 8000)
(cd eval && uv run python -m iaudit_eval.server.app)   # 127.0.0.1:8100
(cd frontend && VITE_MOCK=true npm run dev)             # Audit mock mode
```

In mock mode upload `docs/contracts/examples/request.json`. Mock mode covers eaudit only; Eval has no mock mode ([eval UI](../reference/eval-ui.md)).

## Offline checks

No key or network needed.

```bash
cd engines/eaudit
uv run pytest -q
uv run ruff check src tests eval
uv run python -m eval.run --mode oracle --gate poc   # ADHD oracle gate

cd ../eval
uv run pytest
uv run ruff check src tests

cd ../frontend
npm test            # includes mock fixture validation (src/fixtures/fixtures.test.ts)
npm run typecheck
npm run build
```

Docs only: `cd engines/eaudit && uv run pytest tests/test_docs_drift.py -q`. More: [running-tests.md](running-tests.md), [frontend.md](frontend.md), [evaluation.md](evaluation.md).

## Owner live checks after taxonomy v1 / contract 0.0.1

These need a key, spend money and are not run by agents. Start a cost-capped pilot first where a command offers `--max-cost`.

- [ ] **a. `scripts/dev.sh` live smoke.** Run `scripts/dev.sh`: all three services come up and print the Ready block. Ctrl-C, then confirm no orphans (for example `ss -ltnp | grep -E ':(8000|8100|5173)\b'` is empty). Repeat with `--stub`. Source: [scripts/README.md](../../scripts/README.md).
- [ ] **b. Backend live smoke.** Start `IAUDIT_PIPELINE=full uv run uvicorn eaudit.app:app --port 8000` in `engines/eaudit/` with a key, then `uv run python -m eval.smoke --base-url http://localhost:8000`. All 9 fixtures PASS; note the cost ([pre-release-checklist.md](pre-release-checklist.md) step 3).
- [ ] **c. Ten boundary pairs.** `engines/eaudit/tests/test_check_boundary_pairs.py` uses scripted verifier output, so it runs offline only; the repo documents no live mode for it. To see live behaviour, send the claims from the file through the review UI or `POST /v1/audit` and compare with the asserted concern sets. Do not expect a command.
- [ ] **d. TofuEval.** In the Eval tab: dataset TofuEval, split `dev`, a small N (for example 5) with a max cost, then the full dev split; check the estimate, progress, metrics and an item ([eval UI](../reference/eval-ui.md), [frontend.md](frontend.md#before-a-release)). Run the `test` split once, at the end only; the repeated use compromises the holdout (`test_split_note` in `eval/datasets/eaudit/tofueval/metadata.json`).
- [ ] **e. ADHD buckets 3 and 8 precision, before vs after.** Bucket numbers are mission checks (3 wrong attribution, 8 context stripping). Run `uv run python -m eval.run --mode e2e --live --max-cost <USD> --out <dir>` in `engines/eaudit/` on the new prompts, and the same on the pre-taxonomy commit, then `uv run python -m eval.compare a/report.json b/report.json`. Rows under 5 faults are "indicative only" ([evaluation.md](evaluation.md#reading-a-report)). Check that `--out` and the report file layout match your run; the repo does not document a "before" baseline.
- [ ] **f. p95 latency vs the 100 s deadline.** `uv run python -m eval.run --mode e2e --live` and read the request p50 and max in the report; also `Server-Timing` in devtools ([latency.md](latency.md#live)). The repo documents p50 and max, not p95; derive it from the TofuEval run's per-item timings if needed. Cap is `IAUDIT_AUDIT_DEADLINE_S` (100); the eval client waits 120 s.
- [ ] **g. End-to-end via the review UI.** `scripts/dev.sh`, upload a real request in Audit, check findings highlight. Saved bodies that fail the current schema show a validation error; run lists, metrics and comparisons still work ([frontend.md](frontend.md#before-a-release)). Other eval UI owner checks: [eval-ui.md](../reference/eval-ui.md#owner-manual-checks).
- [ ] **h. Refresh recordings (prompts changed in taxonomy v1).** In `engines/eaudit/`: `uv run python -m eval.run --mode all --live --record --max-cost 5`, then replay with `--strict-fresh` (for example `uv run python -m eval.run --mode all --strict-fresh`) must pass. Commit only synthetic ADHD recordings ([pre-release-checklist.md](pre-release-checklist.md) step 4, [recorded/README.md](../../engines/eaudit/eval/recorded/README.md)).

Then the rest of [pre-release-checklist.md](pre-release-checklist.md).

## Claude Code skills (thepass)

Open this repo in Claude Code and trust the folder: it prompts to install the `thepass` marketplace and plugin (declared in `.claude/settings.json`).

Manual fallback:

```
/plugin marketplace add tejitpabari99/thepass
/plugin install thepass@thepass
```

## Main app (web + api)

Applies to `web/` and `api/` (not the legacy `frontend/` and `engines/` above). Needs node 22, `uv`, java 21. Install: `(cd web && npm ci)` and `uv sync --all-packages` from the repo root.

**Mode A: web mock (MSW + fake auth).** `cd web && npm run dev:mock` serves `http://localhost:5173` with the API in-browser. No backend or login: sign up with any email and password (auto-verified, in memory, lost on reload).

**Mode B: Firestore emulator + api (stub adapters) + web live.** Real Firebase Auth cannot run locally (no Auth emulator wiring), so use `AUTH_MODE=fake` on the api (`Bearer test:<uid>`) and `VITE_AUTH_MODE=fake` on the web. Open the app as `localhost`, not `127.0.0.1` (api CORS).

Terminal 1, Firestore emulator (from repo root; firestore on 8081):

```bash
npx -y firebase-tools@15.37.0 emulators:start --only firestore --project demo-onolys
```

Terminal 2, api on port 8000 (`mkdir -p /tmp/onolys-blobs` first; env vars are in `api/.env.example`):

```bash
FIRESTORE_EMULATOR_HOST=127.0.0.1:8081 ENV=local SERVICE_MODE=combined AUTH_MODE=fake ADAPTERS=stub \
GCP_PROJECT=demo-onolys AUTH_PROJECT=demo-onolys FIRESTORE_DATABASE='(default)' \
CORS_ORIGINS=http://localhost:5173 FAKE_BLOB_DIR=/tmp/onolys-blobs FAKE_BLOB_BASE_URL=http://127.0.0.1:8000 \
uv run --package onolys-api uvicorn --factory onolys_api.app:create_app --host 127.0.0.1 --port 8000
```

Without `FIRESTORE_EMULATOR_HOST`, `ENV=local` uses the in-memory FakeRepo. Combined mode runs the worker in-process with stub STT and evaluation.

Terminal 3, web live on port 5173 (no vite proxy, hence the absolute API URL):

```bash
cd web && VITE_USE_MOCKS=false VITE_AUTH_MODE=fake VITE_API_BASE_URL=http://127.0.0.1:8000/v1 \
VITE_FIRESTORE_EMULATOR=127.0.0.1:8081 VITE_FIREBASE_PROJECT_ID=demo-onolys VITE_FIRESTORE_DATABASE='(default)' \
npm run dev:live
```

Check: `GET :8000/v1/healthz` returns `{"status":"ok",...}`; `GET /v1/sessions` with `Authorization: Bearer test:alice` returns an empty list.

Not available locally: real auth, real STT/LLM (stub adapters; `ADAPTERS=real` needs GCP creds), the voice relay websocket, the Hosting `/v1` rewrite. The audio `validate` step needs ffmpeg/ffprobe on PATH.

E2E (Playwright, `web/e2e_review`): see its README. Screenshots only with `E2E_SHOTS=1`.
