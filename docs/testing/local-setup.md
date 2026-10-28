# Local setup and live verification

Set up every component, run the offline checks, and work through the owner live checks after taxonomy v1 (contract 1.2.0).

**Audience:** contributors and the repository owner.

## Prerequisites

- [uv](https://docs.astral.sh/uv/) and Python 3.12 (`requires-python = ">=3.12,<3.13"` in `eaudit/` and `eval/`).
- Node and npm. CI uses Node 22; the repo pins no other version.
- For live runs, a provider key that LiteLLM reads. `scripts/dev.sh` checks `ANTHROPIC_API_KEY`, `OPENAI_API_KEY` and `LITELLM_API_KEY` for presence; the default models are Anthropic ([configuration](../reference/configuration.md)). Offline tests and stub modes need no key.

## One-time setup

```bash
(cd eaudit && uv sync)
(cd eval && uv sync)
(cd frontend && npm ci)
```

Frontend env: `cp frontend/.env.example frontend/.env.local` (only for running Vite by hand; `scripts/dev.sh` sets its own). See [frontend README](../../frontend/README.md).

Eval datasets: the ADHD fixtures ship in `eaudit/eval/`; no download. TofuEval needs a download (licensed text, stored under `eval/data/`, gitignored): in the Eval tab pick TofuEval and click **Download data**, or `POST /datasets/tofueval/download` ([eval API](../reference/eval-api.md), [eval UI](../reference/eval-ui.md#start-download-watch-and-abort)). Confirm the status is `ready` and inspect the hashes in `eval/data/tofueval/download.json` ([eval README](../../eval/README.md#manual-owner-steps)).

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
| Web (Audit and Eval tabs) | `http://localhost:5173` |

Ports are fixed by the script. Ctrl-C stops all three. Details: [scripts/README.md](../../scripts/README.md).

Components alone:

```bash
(cd eaudit && uv run uvicorn eaudit.app:app --port 8000)
(cd eaudit && IAUDIT_PIPELINE=stub uv run uvicorn eaudit.app:app --port 8000)
(cd eval && uv run python -m iaudit_eval.server.app)   # 127.0.0.1:8100
(cd frontend && VITE_MOCK=true npm run dev)             # Audit mock mode
```

In mock mode upload `docs/contracts/examples/request.json`. Mock mode covers Audit only; Eval has no mock mode ([eval UI](../reference/eval-ui.md)).

## Offline checks

No key or network needed.

```bash
cd eaudit
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

Docs only: `cd eaudit && uv run pytest tests/test_docs_drift.py -q`. More: [running-tests.md](running-tests.md), [frontend.md](frontend.md), [evaluation.md](evaluation.md).

## Owner live checks after taxonomy v1 / contract 1.2.0

These need a key, spend money and are not run by agents. Start a cost-capped pilot first where a command offers `--max-cost`.

- [ ] **a. `scripts/dev.sh` live smoke.** Run `scripts/dev.sh`: all three services come up and print the Ready block. Ctrl-C, then confirm no orphans (for example `ss -ltnp | grep -E ':(8000|8100|5173)\b'` is empty). Repeat with `--stub`. Source: [scripts/README.md](../../scripts/README.md).
- [ ] **b. Backend live smoke.** Start `IAUDIT_PIPELINE=full uv run uvicorn eaudit.app:app --port 8000` in `eaudit/` with a key, then `uv run python -m eval.smoke --base-url http://localhost:8000`. All 9 fixtures PASS; note the cost ([pre-release-checklist.md](pre-release-checklist.md) step 3).
- [ ] **c. Ten boundary pairs.** `eaudit/tests/test_check_boundary_pairs.py` uses scripted verifier output, so it runs offline only; the repo documents no live mode for it. To see live behaviour, send the claims from the file through the review UI or `POST /v1/audit` and compare with the asserted concern sets. Do not expect a command.
- [ ] **d. TofuEval.** In the Eval tab: dataset TofuEval, split `dev`, a small N (for example 5) with a max cost, then the full dev split; check the estimate, progress, metrics and an item ([eval UI](../reference/eval-ui.md), [frontend.md](frontend.md#before-a-release)). Run the `test` split once, at the end only; the repeated use compromises the holdout (`test_split_note` in `eval/datasets/tofueval/metadata.json`).
- [ ] **e. ADHD buckets 3 and 8 precision, before vs after.** Bucket numbers are mission checks (3 wrong attribution, 8 context stripping). Run `uv run python -m eval.run --mode e2e --live --max-cost <USD> --out <dir>` in `eaudit/` on the new prompts, and the same on the pre-taxonomy commit, then `uv run python -m eval.compare a/report.json b/report.json`. Rows under 5 faults are "indicative only" ([evaluation.md](evaluation.md#reading-a-report)). Check that `--out` and the report file layout match your run; the repo does not document a "before" baseline.
- [ ] **f. p95 latency vs the 100 s deadline.** `uv run python -m eval.run --mode e2e --live` and read the request p50 and max in the report; also `Server-Timing` in devtools ([latency.md](latency.md#live)). The repo documents p50 and max, not p95; derive it from the TofuEval run's per-item timings if needed. Cap is `IAUDIT_AUDIT_DEADLINE_S` (100); the eval client waits 120 s.
- [ ] **g. End-to-end via the review UI.** `scripts/dev.sh`, upload a real request in Audit, check findings highlight. Saved 1.1.0 (and older) items no longer open in the item view and show the unsupported-version screen (accepted); run lists, metrics and comparisons still work ([frontend.md](frontend.md#before-a-release)). Other eval UI owner checks: [eval-ui.md](../reference/eval-ui.md#owner-manual-checks).
- [ ] **h. Refresh recordings (prompts changed in taxonomy v1).** In `eaudit/`: `uv run python -m eval.run --mode all --live --record --max-cost 5`, then replay with `--strict-fresh` (for example `uv run python -m eval.run --mode all --strict-fresh`) must pass. Commit only synthetic ADHD recordings ([pre-release-checklist.md](pre-release-checklist.md) step 4, [recorded/README.md](../../eaudit/eval/recorded/README.md)).

Then the rest of [pre-release-checklist.md](pre-release-checklist.md).
