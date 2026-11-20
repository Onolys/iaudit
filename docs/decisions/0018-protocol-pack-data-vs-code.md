# 0018. Protocol packs: data first, three code hooks, safe formulas

**Audience:** contributors.

**Status:** accepted. Measured live 2026-11-20 (Task 14); the check passes with the engine default params.

**Context.** `paudit` rates a session against a protocol (first pack: MITI 4.2.1). Hard-coding MITI in the engine would block other protocols and put protocol facts in engine code. A rules language in YAML would be a second programming language to maintain. See [ADR 0005](0005-models-propose-code-decides.md): models propose, code decides.

**Decision.**

- **Pack as data.** Everything protocol-specific lives in `protocols/<id>-<version>/`: `pack.yaml` (items, rules, volley, summaries, input checks, params, caps, compare, source), `rating.schema.json`, `prompts/`, `report.yaml`, `fixtures/` and an optional `rules.py`. The engine holds no MITI strings and no model ids; a grep test enforces it. Packs are trusted repo code, not user uploads.
- **Declarative rules.** The engine implements a small set of generic rule kinds (`one_code_per_utterance`, `max_per_unit`, `exclusive_group`) and generic input checks; the pack sets their parameters. A global score cap exists only where the pack lists it with the manual page cited (`caps[]`); the engine has no cap of its own.
- **Three optional hooks** in `rules.py`: `check_input` (extra input warnings), `validate_codes` (may only lower counts, never add or invent a code) and `compute_summary` (a summary a formula cannot express). All are pure functions. MITI ships one real hook, `check_input`.
- **Safe-expression formulas.** Summary scores are whitelisted arithmetic over item ids (`cr/(sr+cr)`), parsed with `ast`, no names outside the pack's items, no calls, no `eval`. Division by zero gives `null`.
- **Versions.** `pack_format` is `"0.0.1"` and the result schema `schema_version` is `"0.0.1"`; no back-compat, bump freely (project rule). The loader validates the pack against `pack.schema.json`, runs parity checks (rating keys equal item ids, formula names, prompts present) and raises `PackError` at load only. `pack_hash` covers `pack.yaml`, `rules.py`, `rating.schema.json`, `prompts/` and `report.yaml` (not fixtures) and goes into `run_info`.
- **Scope cuts (After launch).** A toy second pack, a malformed-pack test set, N=3 fixtures with mean/range presentation, and an `eval/datasets/paudit` hook. The loader, schema and grep test stay.

**Alternatives.** All rules in Python (MITI leaks into the engine, harder to diff); all rules and predicates in YAML (a language to design and test); `eval` for formulas (code injection).

**Consequences.** A new protocol is mostly a new folder plus, rarely, one new generic rule kind in the engine. Hooks run with full Python privileges, so packs must be reviewed like code. Quality is proven by `python -m paudit.cli check --pack miti@4.2.1 --preset <name>`, which runs the fixtures on the live model and exits non-zero past `fixtures/thresholds.yaml`. See [engines/paudit](../../engines/paudit/README.md).

## Measurements

Live run 2026-11-20, `python -m paudit.cli check --pack miti@4.2.1 --preset default`, exit 0 (PASS), model `claude-sonnet-5-5` on routes `paudit_code` and `paudit_globals` (`config/prod/routes.yaml`; `config/staging` is identical for these routes). `default` is the only offered preset (the staging file also has `test-broken-*` failure-injection presets, not for users). Three synthetic fixtures, N=1, one code batch each, 3 runs, 56 s wall. Thresholds from `fixtures/thresholds.yaml`.

| Item | Result | Limit |
|---|---|---|
| count MAE | 0.40 | <= 1.5 |
| globals within 1 | 1.00 | >= 0.75 |
| bad-output rate (retry or halving) | 0.00 (0 of 6 calls) | <= 0.10 |
| truncation | none; every call `attempts 1`, `ok` | none |
| p95 latency (max of 3 runs) | 23.8 s (good 23.8, poor 18.6, short 11.1) | <= 90 s |
| tokens per run (max) | 21,552 (good 21,552, poor 20,897, short 17,158) | <= 120,000 |
| cost per run (estimate) | about $0.09 (good_practice); about $0.27 for all 3 runs | n/a |

Per call (probe over the same fixtures, second run, so cache reads show):

| Fixture | Call | Input | Output | Cache read | Output vs cap | Latency |
|---|---|---|---|---|---|---|
| good_practice | globals | 4,280 | 1,233 | 2,819 | 41% of 3,000 | 8.8 s |
| good_practice | code | 5,864 | 2,753 | 4,482 | 34% of 8,000 | 19.5 s |
| poor_practice | globals | 4,070 | 1,325 | 2,819 | 44% of 3,000 | 7.7 s |
| poor_practice | code | 5,666 | 2,531 | 4,484 | 32% of 8,000 | 15.7 s |
| short_session | globals | 3,374 | 867 | 2,819 | 29% of 3,000 | 6.4 s |
| short_session | code | 4,983 | 629 | 4,486 | 8% of 8,000 | 7.9 s |

Cost is an estimate, not billed: it assumes Sonnet list prices of $3 per million input, $15 per million output and $0.30 per million cache-read tokens (check current prices); the token counts are measured. The first run's input is higher than shown because the cache prefix is written once.

**Final params.** No change. The pack ships no `params`, so the engine defaults apply: `volleys_per_call` as in the engine, `code_max_tokens` 8000 and `globals_max_tokens` 3000. Peak output used 34% of the code cap and 44% of the globals cap, so neither truncates; p95 is a quarter of the 90 s target. **Fallback applied:** none.

**Caveat.** The fixtures are short (one code batch each). A long session splits into several batches that run warm-first then in parallel (Decision 15), so latency grows with the longest batch, not the volley count, but a 60-minute session has not been measured here. Re-run this check when the prompts, route model or `volleys_per_call` change; a code-output peak above about 6,000 tokens is the signal to lower the batch size before raising `code_max_tokens`.
