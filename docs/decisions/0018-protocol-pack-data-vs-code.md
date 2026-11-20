# 0018. Protocol packs: data first, three code hooks, safe formulas

**Audience:** contributors.

**Status:** accepted. Measurements below are pending.

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

Pending: filled in from the live check once Task 14 records it.

| Item | Result |
|---|---|
| count MAE | pending |
| globals within 1 | pending |
| bad-output rate | pending |
| p95 latency | pending |
| tokens per run (max) | pending |
