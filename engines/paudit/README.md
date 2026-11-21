# paudit

Protocol-audit engine. Takes a transcript, a pack reference (`miti@4.2.1`) and params; returns a typed result (`paudit-result.schema.json`, version 0.0.1): per-utterance behaviour codes with located quotes, counts, summary scores against reference levels, globals with cited lines, warnings and `run_info`. Models propose, code decides. The engine knows nothing about MITI; the pack does. Why: [ADR 0018](../../docs/decisions/0018-protocol-pack-data-vs-code.md).

## Layout

| Path | Holds |
|---|---|
| `src/paudit/pack.py`, `schemas/pack.schema.json` | Pack loader, schema and parity checks, `pack_hash` |
| `src/paudit/hooks.py` | The three optional `rules.py` hooks |
| `src/paudit/formula.py` | Safe arithmetic evaluator for summaries |
| `src/paudit/prepare.py`, `code_pass.py`, `globals_pass.py`, `score.py` | Input checks and volleys, code pass, globals pass, counts and summaries |
| `src/paudit/engine.py`, `result.py`, `schemas/paudit-result.schema.json` | Run, aggregate, result model and schema |
| `src/paudit/cli.py`, `check.py`, `stub.py` | CLI (`run`, `check`), live check, offline stub client |
| `../../protocols/miti-4.2.1/` | The MITI 4.2.1 pack |

## Run

From the repo root (`uv sync --all-packages --frozen` first):

```bash
uv run --package onolys-paudit python -m paudit.cli run --pack miti@4.2.1 --transcript f.json --params p.json
uv run --package onolys-paudit pytest engines/paudit -m "not live"
```

`run` works offline with the stub client. Live runs need a provider key for the route preset.

## Live check

```bash
uv run --package onolys-paudit python -m paudit.cli check --pack miti@4.2.1 --preset default
```

Runs the pack fixtures on the real model and prints count MAE, globals within 1, bad-output rate, p95 latency and tokens. Exits non-zero past `protocols/miti-4.2.1/fixtures/thresholds.yaml`. Run it once per preset before offering that preset, and after a prompt or route change.
