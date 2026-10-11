---
status: approved
summary: Five core 07a tasks (ADHD fixtures, 8 variants, expected JSON, self-tests, smoke script); 07b harness is one gated optional row.
date: 2026-10-11
---
# Tasks: 07 Eval (07a core, 07b optional)

Source of truth: [PRD.md](PRD.md). 07a builds the ADHD faithful fixture plus 8 single-fault variants as contract requests, simple expected JSON, and a pass/fail smoke script in `backend/eval/`. POC gate: faithful returns no concerns and all 8 variants (V5 included, 07 O-3) return their expected verdict and concern.

| # | Task | Depends on | Status |
|---|---|---|---|
| 1 | ADHD 26-turn faithful fixture with sha256 pin | 01 | done |
| 2 | `spec.json` and `build_adhd.py` generating the 8 variants | 1 | done |
| 3 | Expected JSON per fixture | 2 | todo |
| 4 | Core self-tests: schema-valid requests, byte-identical rebuild | 3 | todo |
| 5 | `eval/smoke.py` pass/fail runner | 4, 06 | todo |
| 6 | [OPTIONAL, gated] 07b harness and optional items | all core in every SP | todo |

## Task 1 — Faithful fixture
What it is / what it means: The ADHD interview as a contract request (R1 layout, R2, D1).
What changes at a high level: `backend/eval/data/adhd/` layout; 26 turns copied verbatim from the brainstorm (speakers `clinician1`, `alex1`, `sam1`; ids `t0..t25`) and the faithful assessment; a test pins the transcript sha256.
Done when: the faithful request validates via 01 `validate_request` and the pin test passes.

## Task 2 — Variants
What it is / what it means: Eight one-edit variants, one fault each (R3, D2, D3).
What changes at a high level: `spec.json` holds each variant's op, target and injected sentence; `build_adhd.py` writes the requests. V1 uses the approved wording "Alex loses attention in every meeting, several times a day." (resolved O-13).
Done when: the builder writes 9 schema-valid requests, each differing from the faithful one by exactly one edit.

## Task 3 — Expected JSON
What it is / what it means: Simple per-fixture expectations (R5a, D6, D10).
What changes at a high level: The builder writes `expected/<fixture>.json` from the R3 table. Faithful expects every claim `supported` with no concerns. V2 lists `contradictory_evidence` under `concerns_allowed` (resolved O-1). V4 needs no evidence (resolved O-2). V5 expects `insufficient_evidence` + `timeframe_mismatch` and is gated.
Done when: all 9 expected files parse and each `target_text` is an exact substring of its section.

## Task 4 — Self-tests
What it is / what it means: Fixtures stay reproducible (R10 core subset).
What changes at a high level: Default-pytest tests that the requests validate, rebuilding is byte-identical to the committed files, and expected files are well formed.
Done when: `uv run pytest` runs them offline.

## Task 5 — Smoke script
What it is / what it means: The POC gate as one command (R14).
What changes at a high level: `uv run python -m eval.smoke [--base-url URL | --inprocess] [--only ...]` sends each fixture to `POST /v1/audit`, finds the target claim by span overlap, prints expected vs actual and PASS/FAIL per fixture, and exits 1 on any failure. Collateral concerns on other claims are printed, not gated (resolved O-9). Prints no transcript text.
Done when: it runs in-process with the stub pipeline (all FAIL, proving the plumbing) and, with 06 and a key, reports all 9 fixtures.

## Task 6 — [OPTIONAL, gated] 07b harness and optional items
What it is / what it means: The PRD's Optional tier, started only after all core work in every sub-project is done.
What changes at a high level: Gold JSONL, three modes and adapters, per-bucket P/R/F1, replay manifest and `--gate poc`, oracle and scorer tests, leak test, V4-noroles, `adhd-multi` (waits for user text, O-5), CDR cleanup spec (waits for the file, O-10/O-11), baseline hook.
Done when: each optional acceptance part passes.
