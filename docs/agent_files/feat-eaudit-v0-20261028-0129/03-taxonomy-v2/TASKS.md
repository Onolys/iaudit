---
status: draft
summary: Eight tasks adding four detected concern types, narrowing three, rewriting the TofuEval mapping and the mission (17 checks, 4 groups); mission gated on owner approval; no live runs by agents.
date: 2026-10-28
---
# Tasks: SP03 Taxonomy v2

Source of truth: [PRD.md](PRD.md). Add `opinion_as_fact`, `calculation_error`, `meaning_shift` and `unsupported_inference` on the existing "verifier observes, code gates and decides, fixed templates explain" path, narrow three older types, and rewrite the TofuEval mapping as a refinement. Runs after SP01 (rename) and SP02 (17-type enum, `group`, schemas 0.0.1); paths are post-rename. Agents run only offline checks.
Contract versioning rule: all schemas are `schema_version` "0.0.1"; the project is not deployed, so no legacy/back-compat code, version history or migration; a file or body not conforming to the current schema just shows a validation error and the owner deletes it.

| # | Task | Depends on | Status |
|---|---|---|---|
| 1 | Mission rewrite (gated on owner approval) | owner approval of wording | todo |
| 2 | Detection: flags, gates, verdicts, failed-inference relabel | 1 | todo |
| 3 | Dedup chain, yields and REVISABLE | 2 | todo |
| 4 | Prompt, few-shot, atomizer check, templates, labelling rules | 2, 3 | todo |
| 5 | Gold check for failed-inference relabelling | 2 | todo |
| 6 | TofuEval mapping rewrite | 2 | todo |
| 7 | Synthetic cases and boundary pairs | 4, 5 | todo |
| 8 | Offline verification and acceptance sweep | 1-7 | todo |

## Task 1 — Mission rewrite (gated)
What it is / what it means: The mission governs scope, so it lands first and only once the owner approves the 17-check, 4-group wording (Req 5, Decision 9, Manual steps).
What changes at a high level: `docs/mission.md` lists 17 checks in enum order (14 to 17 appended), each with definition and example, plus a 4-group section using the Req 2 map. Checks 6, 8 and 13 are narrowed. The "reported explanations and assessor inferences are different" principle links to check 14. The score-calculation boundary bullet stays for scoring rules only, with totals of interview figures placed under check 15.
Done when: the mission matches the approved wording, agrees with the enum and group map, and no code change precedes it. All suites stay green.

## Task 2 — Detection: flags, gates, verdicts
What it is / what it means: The four types end to end in the checker (Req 1, 3, Architecture detection, Decisions 1, 2, 10).
What changes at a high level: Add the four flag types and map each to its concern; include them in the set that keeps a `not_addresses` item as partial support. Add the code gates: opinion needs an unhedged claim reported by assessor or unspecified (plus assessor-sourced causal link where one covers it); calculation needs a number token in the claim and at least two across cited turns; meaning_shift needs known non-empty keys. A failed gate suppresses and counts the flag. A failed inference with entailing premises becomes `unsupported_inference` instead of `unsupported_claim`, and a scope-broadening flag is allowed when items entail the narrower claim. Verdicts: partially supported, contradicted only on the verifier's `contradicts` relation, failed inference stays insufficient evidence.
Done when: unit tests with scripted verifier output cover each type's verdict and role and each gate's suppression, plus the failed-inference relabel. All suites green.

## Task 3 — Dedup chain, yields, REVISABLE
What it is / what it means: One discrepancy yields one concern, and revisions stay checkable (Decisions 3, 7).
What changes at a high level: Insert `meaning_shift` in the dedup chain before contradictory evidence. Opinion suppresses certainty, causal-link and inference on shared keys; causal link suppresses inference; calculation suppresses quantity. Existing quantity yields are kept and ordering follows the enum. Add opinion_as_fact, meaning_shift and unsupported_inference to the revisable set; exclude `calculation_error`.
Done when: tests pin each dedup and yield outcome, and the revisable set excludes calculation_error. All suites green.

## Task 4 — Prompt, few-shot, atomizer check, templates
What it is / what it means: The wording side of the taxonomy (Req 4, 7, Architecture prompt and templates, Decision 8, atomizer resolution).
What changes at a high level: In the checker system prompt add the four flag definitions with their boundaries, delete the two labelling rules, and drop the secondhand clause from certainty and the broadening clause from context stripping. Add about eight fictional few-shot examples (a positive and a faithful negative per new type) outside TofuEval vocabulary. Check the atomizer prompt so "mother believes X" yields the believer as reporter; tweak only if needed. Add the four fixed neutral templates and trim the three narrowed ones. Prompt changes make recorded fixtures stale: keep CI green in replay mode per ADR 0013 without live calls and leave re-recording to the owner.
Done when: template tests show no digits, transcript text or banned words, `test_prompt_leakage` passes, no remnant of the two labelling rules, and the suite is green offline.

## Task 5 — Gold check for failed-inference relabelling
What it is / what it means: Relabelling `unsupported_claim` to `unsupported_inference` may touch gold (resolved risk).
What changes at a high level: Inspect ADHD and oracle gold for bucket-1-via-inference cases affected by the relabel. Regenerate gold only if affected.
Done when: the outcome (unaffected or regenerated) is recorded in the task commit, and all suites are green.

## Task 6 — TofuEval mapping rewrite
What it is / what it means: Mapping becomes the crosswalk in the PRD so each of our types appears in at most one TofuEval row (Req 6, Decisions 4, 5, 6).
What changes at a high level: Replace `mapping.json` in place with the seven-row table: NMS and RE are now concern-scored, Opinion as Fact maps to `opinion_as_fact` only (meetingbank override removed), Mis-Referencing keeps the mediasum restriction. The five unmapped types stay unscored. Set `mapping_version` to "0.0.1" and delete the `mapping_history` clause in the `mapping.py` docstring. Update mapping tests.
Done when: mapping validates against the enum, every mapped concern exists, no type is in two rows, tests no longer treat NMS and RE as recall-only, and no `mapping_history` remains. All suites green.

## Task 7 — Synthetic cases and boundary pairs
What it is / what it means: Offline evidence per new type (Acceptance, Goals).
What changes at a high level: Add to the synthetic dataset, per new type, at least two fictional flagged items and one faithful near-miss. Add backend boundary-pair tests (certainty vs opinion, calculation vs quantity, meaning_shift vs negation vs wrong_attribution). Touch the leakage config only if needed.
Done when: zero-spend CI is green and `test_prompt_leakage` finds no TofuEval or brief text.

## Task 8 — Offline verification and acceptance sweep
What it is / what it means: Confirm the PRD acceptance list that agents can check.
What changes at a high level: Run backend tests, lint and frontend typecheck/tests; confirm mission, enum, schema and group map agree. Fix gaps only within SP03 ownership.
Done when: all suites pass and every non-deferred acceptance item is satisfied.

## Owner manual steps
- Approve mission wording (17 checks, 4 groups) before Task 1 lands.
- Re-record LLM fixtures (needs API keys) after the prompt changes; agents make no live calls.
- TofuEval baseline, before/after and test runs are deferred and not a merge gate; when run, mapping is frozen, tuning is on dev only, and the report notes concern-match is not comparable across mappings.
