# Evaluation harness

Run from `eaudit/`. Results are labelled split `poc-all`: a smoke check on data the authors have
seen, not a generalization estimate. Reports are per bucket (mission check 1-13); there is no
overall score.

| Command | What it does |
|---|---|
| `uv run python -m eval.smoke` | The POC gate through `POST /v1/audit` (see `eaudit/README.md`). |
| `uv run python -m eval.run --mode oracle --gate poc` | Gold echoed through the assembler. Proves the harness without an LLM. |
| `uv run python -m eval.run --mode gold\|linked\|e2e` | Gold: checker alone on gold claims and evidence. Linked: linker then checker. E2E: full pipeline. |
| `--live [--record]`, `--max-cost USD`, `--strict-fresh` | Call providers (keys needed), write recordings, cap the estimated cost, fail on stale recordings. |
| `uv run python -m eval.compare a/report.json b/report.json` | Per-bucket F1 deltas; flags a gain of 0.05 or more. |
| `--baseline NAME` | Bucket-1 baseline hook. Registered baselines are not installed. |

Not built yet: `adhd-multi` (waits for approved content, 07 O-5) and the CDR cleanup script
(waits for the files, 07 O-10 and O-11).
