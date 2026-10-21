---
status: draft
summary: Seven tasks adding quantity_mismatch (check 13), widening two definitions, contract 1.2.0, ADR 0015; mission edit gated on owner approval; no live runs by agents.
date: 2026-10-20
---
# Tasks: A1 Taxonomy v1

Source of truth: [PRD.md](PRD.md). Add `quantity_mismatch` as the 13th enum value, detected by the existing "LLM observes, code decides" path. Widen `wrong_attribution` and `context_stripping`, add two labelling rules, and move the contract to 1.2.0 in one coordinated change. Mapping v1.0.0, ADHD gold and the TofuEval projection stay untouched. Agents run only offline checks.

| # | Task | Depends on | Status |
|---|---|---|---|
| 1 | Mission amendment (gated on owner approval) | owner approval of wording | done |
| 2 | Backend detection: enum, flag, guards, dedup | 1 | done |
| 3 | Prompt, few-shot, templates, labelling rules | 2 | todo |
| 4 | Contract 1.2.0, ADR 0015, frontend enum and label | 2 | todo |
| 5 | New mock fixture and boundary-pair tests | 3, 4 | todo |
| 6 | Docs sweep for "12" references and concepts | 1, 4 | todo |
| 7 | Offline verification and acceptance sweep | 1-6 | todo |

## Task 1 — Mission amendment (gated)
What it is / what it means: The mission governs scope, so the arithmetic clarification and check 13 land first (Req 9, Decision 3). Blocked until the owner approves the PRD's draft wording table.
What changes at a high level: `docs/mission.md` edited exactly as approved: "thirteen" checks, widened checks 3 and 8, new row 13, the narrowed score-arithmetic boundary, and the "a stated figure is a claim" interpretation bullet.
Done when: the mission matches the approved wording exactly, and no code or contract change precedes it.

## Task 2 — Backend detection
What it is / what it means: The `quantity_mismatch` concern end to end in the checker, with deterministic guards (Req 2, 3, 4, Decisions 4-6).
What changes at a high level: Append the enum value in the Python model and add the flag type. Map the flag to the concern. Suppress and count a flag unless the claim and a cited turn both contain a number token. Count `not_addresses` items under the flag as partial support. Reorder the dedup chain so frequency beats quantity and quantity beats contradictory evidence. Verdict is partially supported, or contradicted if the verifier says `contradicts`.
Done when: unit tests cover D8/D4 outcomes, both dedup orders, guard suppression, and `not_addresses` retention.

## Task 3 — Prompt, few-shot, templates
What it is / what it means: The wording side of the taxonomy, with no schema effect (Req 5, 6, 7, Decisions 7, 8).
What changes at a high level: Add the flag definition, rounding rule (dropped decimals are not a mismatch), widened `experiencer` and `context_stripping` lines, and the two labelling rules to the system prompt. Add about five fictional few-shot examples. Add the neutral quantity template, widen the two other templates, and make `quantity_mismatch` revisable.
Done when: template tests show no digits, transcript text or banned words, and `test_prompt_leakage` passes with no TofuEval or brief-sample text.

## Task 4 — Contract 1.2.0 and ADR
What it is / what it means: The coordinated version and enum change (Req 1, 8, Decisions 2, 9, 10).
What changes at a high level: The schema enum gets 13 values with the new one last, and all three schemas move to 1.2.0. Every backend, frontend, mock validator, ADHD request and test version string moves together. Frontend concern types and the "Quantity mismatch" label are updated. Contract README and examples are updated. ADR 0015 and its index line go in the same commit.
Done when: no `"1.1.0"` contract string remains outside ADR text, old versions are rejected everywhere, and the label test covers 13.

## Task 5 — Fixture and boundary pairs
What it is / what it means: Fictional coverage for the new type and its boundaries (Req 10, Decision 13).
What changes at a high level: Add a new mock `11-...` fixture (medication/team size) containing a `quantity_mismatch` concern. Add 10 fictional boundary pairs run with scripted verifier outputs, asserting exactly one type for rate-vs-count and the other listed cases. Update mock README counts to 13.
Done when: the fixture passes the mock `validate.py` and the pairs pass in CI.

## Task 6 — Docs sweep
What it is / what it means: Bring prose in line with 13 checks (change-surface table).
What changes at a high level: Update the "12" references in review-ui, evaluation, how-an-audit-decides, the mock and real example READMEs, the eval README and the TS comment. Add a boundary note in the severity-and-frequency concept doc and a short quantity paragraph with the labelling rules. Leave historical ADRs and age-meaning "twelve" alone.
Done when: a re-grep finds only intended leftovers, including a check for hard-coded 12 in `eval/` and `frontend/src/eval/`.

## Task 7 — Offline verification
What it is / what it means: The agent-runnable acceptance gates; no live calls, evals or TofuEval runs.
What changes at a high level: Run backend pytest, ruff, the oracle poc gate, and frontend typecheck and test. Confirm ADHD gold for buckets 1-12 and the oracle buckets are unchanged, and that `mapping.json` is untouched. Fix any regressions.
Done when: all offline acceptance items pass.

## Owner manual checks (not tasks)
- Approve the mission wording before Task 1; confirm ADR number and 13-label wording.
- Record the TofuEval dev baseline in the eval UI before the A1 prompt changes merge, then run the after pass under mapping v1.0.0. Report per-group recall, the `quantity_mismatch` count and the concern-match caveat. Run the test split once, at the end.
- Run the 10 boundary pairs live, compare ADHD bucket 3 and 8 precision and p95 latency against the 100 s deadline, and do the final end-to-end test including saved-item replay.
