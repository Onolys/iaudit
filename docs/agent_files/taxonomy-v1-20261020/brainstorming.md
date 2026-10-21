---
status: approved
summary: Project A, taxonomy v1 - add quantity_mismatch (check 13), widen wrong_attribution and context_stripping, add two labelling rules; each justified from the mission, not from TofuEval.
date: 2026-10-20
---

# Project A: taxonomy v1

## 1. TL;DR

Add one concern, `quantity_mismatch` (a stated value that does not match the interview), as mission check 13. Widen two definitions: `wrong_attribution` to "wrong person, source, or entity", and `context_stripping` to "dropped qualifier or broadened scope". Add two labelling rules with no new type: a changed action is `contradictory_evidence` or `unsupported_claim`; two true facts merged into an invented link is `unsupported_claim`. Every change is justified from the mission and interview use (clinical, hiring, research). TofuEval only revealed the gap. Built last, so the TofuEval eval gives a clean before/after. Contract goes up a minor version; an ADR records it.

## 2. Problem

The 12 concern types were written from the mission's examples, not tested against a broad set of real distortions. A seeded sample of TofuEval sentences showed a residue the 12 types do not name: wrong numbers, wrong entities, broadened scope. Today these land under the generic `unsupported_claim` or `contradictory_evidence`, which hides a reviewer-useful signal (a wrong dose is not the same finding as an unsupported remark). Meanwhile some of this is already in the mission text but not in the definitions the code and contract use (an omitted qualification that changes meaning; "who experienced or reported" generalized to what a fact belongs to).

Constraint from the user: no edits just to move a test score. A change goes in only if the mission and interview use justify it on their own.

## 3. Decision log

| Decision | Alternative rejected | Why |
|---|---|---|
| Add `quantity_mismatch`: a stated value that does not match the source (money, counts, doses, ages, tallies, arithmetic) | Fold numbers into `frequency_severity_inflation` | Wrong values are not directional exaggeration; a dose of 20 mg stated as 10 mg is neither "more" nor "worse" frequency or severity |
| Same | Fold numbers into `contradictory_evidence` | Loses a high-value, filterable clinical signal (doses, counts, ages) behind a generic label |
| Boundary: how often / how bad / how long stays in `frequency_severity_inflation`; dates and timing stay in `timeframe_mismatch` | Move all numerals to the new type | Existing rate-to-bucket logic and ADR 0010 behavior must not regress; a numeral is not the unit of classification, the thing measured is |
| Append as the 13th value in the enum | Insert next to `frequency_severity_inflation` | Eval bucket = 1-based enum position (`backend/eval/gold.py:17`); appending keeps buckets 1-12 and all gold stable |
| Widen `wrong_attribution` to "wrong person, source, or entity" | Separate `wrong_entity` concern | Same failure shape (right content, wrong owner); a second type splits one reviewer action into two. Clinical: current vs previous medication |
| Wrong action ("announced" becomes "approved"): no new type. `contradictory_evidence` if the source states the actual action, else `unsupported_claim` | Fold into `wrong_attribution` | The entity is right; the event changed. Existing types already express "source says otherwise" vs "source does not say" |
| Labelling rule is an iAudit rule; the eval does not map it back to a TofuEval category | Add a TofuEval-shaped category | Keeps the taxonomy driven by the mission, not the benchmark |
| Widen `context_stripping` to "dropped qualifier or broadened scope" | Separate `overgeneralization` concern | Mission check 8 already covers an omitted qualification that materially changes meaning; narrowing "some members" to a category is the same mechanism |
| Two true facts merged into an invented link: `unsupported_claim` | Broaden `unsupported_causal_link` to "unsupported relationship" | Rare in sample (1 of 84); a causal link is the mission's specific concern. Revisit if the rate rises |
| Contract is a minor bump (new allowed value), ADR written, mission table 12 to 13 | Keep 1.0.0 silently, as ADR 0010 did | ADR 0010 changed wording only; this adds an enum value, which the contract's own versioning rule says is minor |
| TofuEval category mapping used by the eval is frozen and versioned; tuning on dev split only | Re-map after seeing results | Prevents label drift from inflating the after-score |

## 4. Evidence that prompted this

Labelled plainly: an LLM-judged sample, **not gold**, and not human-adjudicated.

| Evidence | Result |
|---|---|
| Seeded sample, 84 dev inconsistent TofuEval sentences, LLM judgment | About 85% map to existing concerns; 13 of 84 (~15%) fit none |
| The 13 | Wrong object/action/term 4; overgeneralization/scope 3; number/quantity 3; merged facts, omission-in-list, document-type mislabel 1 each |
| Examples in the 3 number cases | $10.6B reported as $10B; vote tally wrong; fleet total miscomputed |
| Keyword heuristic over all 644 dev explanations | Number-related ~31% (inflated by words "year", "vote"; 112 rows have digits in both summary and explanation); scope/generalization ~19% |

Sample size is small and the 13 split into groups of 1 to 4. These numbers say "look here", not "this is the rate". TofuEval categories are from Appendix G.1 of the paper (NAACL 2024): Extrinsic Information; Mis-Referencing (a grounded property or event attributed to a different grounded entity, so entity-general); Stating Opinion as Fact; Reasoning Error (explicitly includes arithmetic errors and wrong relations); Tense/Aspect/Modality; Contradiction (negation or antonym); Nuanced Meaning Shift. The existing crosswalk (INVESTIGATION.md section 5.4.1) already listed "arithmetic mistakes" and "non-person entity reassignment" as reverse gaps with no iAudit concern.

## 5. Proposed definitions

All examples below are illustrative and fictional, in the style of `docs/mission.md`. Justification is from the mission and interview use, not the benchmark. Final wording is approved at design time.

### 5.1 New: `quantity_mismatch` (check 13)

**Draft definition.** Whether a stated amount, count, value, or calculated figure in the assessment matches the interview: money, doses, ages, counts, tallies, and arithmetic over them.

**Boundaries.**

| Neighbour | Rule |
|---|---|
| `frequency_severity_inflation` | How often, how bad, how long, how intense stays there. A rate ("twice a week") compared to the interview's rate is frequency. |
| `timeframe_mismatch` | Dates, durations-as-timing and past/present placement stay there ("since age 12", "last year"). |
| `contradictory_evidence` | A mismatched number is `quantity_mismatch`, not a second concern; do not stack both for one discrepancy. |
| `certainty_inflation` | "About ten" becoming "exactly ten" is certainty; "ten" becoming "twelve" is quantity. |
| `unsupported_claim` | A number the interview never gives is unsupported; a number the interview gives differently is a mismatch. |

**Illustration (fictional).** Candidate says they managed a team of six; assessment says a team of sixteen. Clinical: patient reports taking 20 mg; assessment records 10 mg. Research: participant says three household members; assessment says five.

**Justification (mission).** The mission's job is to catch an assessment that changes the meaning of its source. A wrong dose, count, or amount changes what happened without any qualifier, direction, or timing change, so none of checks 1-12 name it. Reviewers triaging findings gain from being able to filter the high-stakes numeric class (doses, counts) from general unsupported remarks. It is domain-independent: money in hiring, tallies in research, doses in clinical work.

### 5.2 Widened: `wrong_attribution` to "wrong person, source, or entity"

**Draft.** Whether who or what experienced, reported, or owns something is represented correctly: the person, the source, or the entity the fact belongs to.

**Boundary.** Right owner, wrong event: not attribution (see 5.4). Right fact, wrong period: `timeframe_mismatch` (current vs previous medication is attribution only when the interview treats them as distinct things and the claim attaches the property to the wrong one; if the only error is when, use timeframe).

**Illustration (fictional).** Interview: the old fleet had frequent breakdowns; the replacement fleet is reliable. Assessment attaches the breakdowns to the current fleet. Clinical: side effects the patient attributed to the previous medication are written against the current one.

**Justification.** Mission check 3 is about "who experienced something, who reported it". The principle is that a true statement is attached to the wrong owner. In interviews the owner is often not a person (a medication, a prior employer, a workplace, a program). Treating a person differently from any other owner would give the same failure two labels.

### 5.3 Widened: `context_stripping` to "dropped qualifier or broadened scope"

**Draft.** Whether an omitted qualification, or a widening of scope, materially changes the meaning of a claim: a restriction, condition, or limited group is dropped or replaced by a broader one.

**Boundary.** Broadening that is only more frequent or more severe stays in `frequency_severity_inflation`. Broadening that replaces a specific group, setting, or condition ("some members", "only at work", "with one manager") with a wider one is context stripping. Mission rule retained: not every omission is a concern; it counts only when it changes a claim the assessment makes.

**Illustration (fictional).** Interviewee: some members of the hiring panel raised concerns. Assessment: the panel raised concerns. Clinical: difficulty only in one workplace becomes difficulty at work in general.

**Justification.** Mission check 8's example (difficulty after several nights without sleep becomes an unrestricted claim) is already a scope widening. The definition just states it in both directions of the same mechanism.

### 5.4 Labelling rule: wrong action (no new type)

When the actor is right but the event changed ("announced" becomes "approved", "was offered" becomes "accepted"): `contradictory_evidence` if the interview explicitly states the actual action; otherwise `unsupported_claim`. Justification: the mission already separates "explicit evidence conflicts" from "not established". An iAudit labelling rule only; not mapped to a TofuEval category. Illustration (fictional): the candidate says the offer was extended; the assessment says it was accepted.

### 5.5 Labelling rule: merged facts (no new type)

Two facts each true on their own, joined into a relationship the interview does not give (a contract term length attached to opt-out fees): `unsupported_claim`. If the join asserts cause and effect, `unsupported_causal_link` already applies. Justification: nothing new for the reviewer to act on; the merged claim is not substantiated. Revisit if it recurs (1 of 84 in sample).

## 6. Change surface (verified by grep of `frequency_severity_inflation`, `unsupported_causal_link`, `question_as_answer` outside node_modules and agent_files)

| Area | Path | Change |
|---|---|---|
| Mission | `docs/mission.md` | Table 12 to 13 checks; "The following twelve checks"; check 3 and 8 wording; user approves final text |
| Contract enum | `docs/contracts/audit-response.schema.json` (Concern.type enum, description "checks 1-12") | Add `quantity_mismatch`; update description |
| Contract doc | `docs/contracts/README.md` | Concern table; version text; `"1.0.0"` strings |
| Version | schema, README, frontend `contract/types.ts` (2 literals), `contract/validate.ts:46`, `docs/examples/mock/validate.py:28`, `backend/eval/adhd.py:21`, backend and frontend tests with `"1.0.0"` | Bump (see 6.1) |
| Backend enum | `backend/src/iaudit_backend/models/audit.py` (ConcernType) | Append value last |
| Prompt | `backend/src/iaudit_backend/prompts/check_system.md` (Flags list) and `check_fewshot.json` | Add flag/definition; widened wording; few-shot examples |
| Checker | `backend/src/iaudit_backend/check/models.py` (FlagType), `check/group_a.py`, `check/checker.py` | New flag type, quantity observation path |
| Assembler | `backend/src/iaudit_backend/check/synth.py` (`_FLAG_CONCERN`, `_CHAIN`, `_ORDER`), `check/templates.py` (templates, REVISABLE) | Map, dedup order, explanation template, revision rule |
| Eval buckets and scorer | `backend/eval/gold.py:17` (CONCERNS from enum), `score.py`, `build_adhd.py`, `data/adhd/spec.json`, `gold/`, `expected/`, `tests/` | Bucket 13 appears automatically; check score tables and any hard-coded 12 |
| Eval framework (B, C) | root `eval/` and TofuEval adapter | Add 13 to per-bucket reporting; frozen mapping version |
| Frontend | `frontend/src/claim-detail/concernLabels.ts`, `contract/types.ts` | Label, enum list, tests |
| Fixtures and examples | `docs/examples/mock/*/response.json`, `docs/examples/mock/README.md` ("all 12 concern types"), `docs/examples/real/*/expected.json` | At least one fictional fixture exercising `quantity_mismatch`; update counts |
| Concepts | `docs/concepts/how-an-audit-decides.md`, `docs/concepts/severity-and-frequency.md` (boundary note) | Add boundary; maybe a short quantity concept note |
| ADR | `docs/decisions/0014-...` and `docs/decisions/README.md` | Write: Context, Decision, Alternatives, Consequences, as in ADR 0010 |
| Tests | `backend/tests/test_check_*`, `test_assembler_example.py`, `test_eval_harness.py` | New cases |

### 6.1 Version number

Adding an allowed enum value is **minor** by the contract's own rule. Project B (eval-core) lands first and takes 1.1.0 for `run_info`. So this ships as **1.2.0**, if B has shipped as planned; verify at design time. Risk: the contract says a consumer must reject any other version, so frontend, backend, mocks and validators move together in one release. Because both are additive minors, a single combined bump is also acceptable if B and A are released together; decide at design time.

## 7. How we measure the effect

| Step | Detail |
|---|---|
| Before | Run the TofuEval eval (project C) on the **dev split** with the 12-type taxonomy, before any change. Recorded as the baseline. |
| After | Same dev split, same frozen mapping version, same models, after taxonomy v1. |
| Report | Per native TofuEval group recall (no forced taxonomy mapping, per INVESTIGATION.md 5.4); plus the 13-sentence residue tracked separately. |
| Guardrail | The ADHD harness (`backend/eval`) must stay green; no change to its 12 gold buckets; add bucket 13 cases separately. |
| Discipline | No test-split tuning. Prompt and definition wording is tuned on dev only. Mapping frozen and versioned before the after run. |
| Honest framing | The 13-of-84 sample is LLM-judged, not gold; a change in recall is evidence about the implementation, not proof the taxonomy is right. |

## 8. Non-goals

| Not doing | Why |
|---|---|
| Changing definitions only to raise a benchmark score | User constraint; mission-driven only |
| Separate `wrong_entity`, `overgeneralization`, `wrong_action` types | Rejected above |
| Broadening `unsupported_causal_link` | Rare, deferred |
| Arithmetic or scoring audit | Mission excludes numerical score calculations; `quantity_mismatch` covers a figure stated in the assessment against the interview, not scoring rules |
| Verifying numbers against the real world | Mission is fidelity to the supplied interview only |
| Diagnosis, protocol review, new file formats | Out of mission scope |
| Coverage field or per-type recall guarantees | Contract has none |

## 9. Open risks and cheapest tests

| Risk | Cheapest test |
|---|---|
| Arithmetic vs `numerical score calculations` exclusion in mission | Mission wording: calculated figures only when stated in the assessment about interview facts (counts, totals); score arithmetic stays excluded. Review wording with the user. |
| Boundary with frequency (numbers like "three times a week") is blurry; checker may double-label | Fixture set of 10 fictional pairs; assert exactly one of the two types; ADHD frequency fixtures must not change |
| Widening `wrong_attribution` raises false positives on current vs previous items | Run ADHD harness; compare bucket 3 precision before/after |
| Widening `context_stripping` over-fires on legitimate summarization (mission: summarizing is fine) | Fixtures where generalization is faithful; assert no flag |
| 13-of-84 sample too small or LLM-judged label noise | Re-judge with a second model on the same seeded sample; spot-check by hand 13 rows |
| Version coupling: consumers reject non-matching `schema_version` | Contract and mock validators in CI against the new schema; run frontend contract test |
| Prompt/few-shot growth costs tokens and latency (60 s cap, ADR 0008) | Compare token counts and p95 latency on the ADHD set before/after |
| Order sensitivity: `_CHAIN` and `_ORDER` in `synth.py` decide dedup winner | Unit tests for new precedence over `contradictory_evidence` |

## 10. Links

- [../eval-core-20261020/brainstorming.md](../eval-core-20261020/brainstorming.md)
- [../eval-tofueval-20261020/brainstorming.md](../eval-tofueval-20261020/brainstorming.md)
- [../eval-ui-20261020/brainstorming.md](../eval-ui-20261020/brainstorming.md)
- [../users-codex-eval-investigation-20261020-035707/INVESTIGATION.md](../users-codex-eval-investigation-20261020-035707/INVESTIGATION.md) (section 5.4 and 5.4.1 crosswalk)
- [../../mission.md](../../mission.md)
- [../../contracts/README.md](../../contracts/README.md), [../../decisions/0010-understatement-reuses-inflation-concern.md](../../decisions/0010-understatement-reuses-inflation-concern.md)
- TofuEval paper (NAACL 2024), Appendix G.1 error taxonomy
