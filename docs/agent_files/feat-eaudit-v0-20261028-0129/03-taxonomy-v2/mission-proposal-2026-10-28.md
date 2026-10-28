---
status: draft
summary: Exact mission wording for seventeen checks in four groups, for owner approval before SP03 implementation.
date: 2026-10-28
---
# Proposed mission wording: taxonomy v2

Target: `docs/mission.md`. Source: SP03 PRD Requirements 1, 2 and 5. This document proposes the replacements and additions below for owner review; it does not change the mission. All examples below are fictional illustrations, not quotations or claims about supplied interviews.

All mission text outside the specified replacements and addition stays unchanged, including the seven principles, human-review requirements, four results, evidence limitations, and exclusions for diagnosis, scoring and protocol review.

## 1. Replace the checks introduction

Replace the sentence immediately below `## What the tool checks` with:

> The following seventeen checks define the scope of this build. The examples are illustrative.

## 2. Replace checks 6, 8 and 13

Replace only the corresponding rows in the existing table with:

| Check | What it checks | Example potential discrepancy |
|---|---|---|
| **6. Certainty inflation** | Whether the assessment drops a speaker's hedge or expression of uncertainty and presents the same statement as definite. | The person tentatively estimates that something happened twice; the assessment states that it happened twice as a definite fact. |
| **8. Context stripping** | Whether an omitted qualification or condition materially changes the meaning of a claim. | Difficulty occurring only after several nights without sleep becomes an unrestricted claim about everyday functioning. |
| **13. Quantity mismatch** | Whether a stated amount, count or value in the assessment differs from the figure supplied by the interview. Totals or arithmetic derived from interview figures are checked under check 15. | The person reports taking 20 mg; the assessment records 10 mg. |

Check 6 covers a dropped hedge; a belief or reported view presented as fact belongs to check 14. Check 8 covers an omitted qualifier or condition; an overgeneralization belongs to check 17. These distinctions are expressed by the definitions above and the added rows below.

## 3. Append checks 14–17 to the same table

Append these rows immediately after check 13; retain checks 1–13 in their existing order:

| Check | What it checks | Example potential discrepancy |
|---|---|---|
| **14. Opinion as fact** | Whether a belief, opinion or reported view is presented as an established fact rather than attributed to the person who holds it. | A parent believes the medication causes headaches; the assessment states that the medication causes headaches. |
| **15. Calculation error** | Whether a total or arithmetic result stated in the assessment matches the figures the supplied interview gives. | The interview reports two missed appointments in March and one in April; the assessment gives a total of five. |
| **16. Meaning shift** | Whether the assessment substitutes a word or action whose meaning differs from what the interview describes. | The interview describes a recommendation for physiotherapy; the assessment says physiotherapy was ordered. |
| **17. Unsupported inference** | Whether the assessment asserts a relation between individually supported facts, or generalizes beyond those facts, without support in the supplied interview. | The interview says some panel members raised concerns; the assessment attributes those concerns to the panel as a whole. |

## 4. Add a group section

Insert the following section between the checks table and `### How these checks should be interpreted`:

### How the checks are grouped

The seventeen checks are organized into four groups to help reviewers understand the kind of potential discrepancy. The groups organize concern types; they do not replace the claim's result or determine its severity.

| Group | Checks |
|---|---|
| **Not in interview** | 1. Claim support (`unsupported_claim`); 12. Unsupported causal links (`unsupported_causal_link`); 9. Question mistaken for an answer (`question_as_answer`); 17. Unsupported inference (`unsupported_inference`). |
| **Opposite of interview** | 2. Contradictory evidence (`contradictory_evidence`); 5. Negation reversal (`negation_reversal`). |
| **Changed detail** | 3. Wrong person, source, or entity attribution (`wrong_attribution`); 4. Timeframe mismatch (`timeframe_mismatch`); 13. Quantity mismatch (`quantity_mismatch`); 7. Frequency or severity inflation (`frequency_severity_inflation`); 6. Certainty inflation (`certainty_inflation`); 14. Opinion as fact (`opinion_as_fact`); 15. Calculation error (`calculation_error`); 16. Meaning shift (`meaning_shift`). |
| **Missing context** | 8. Context stripping (`context_stripping`); 10. Correction ignored (`correction_ignored`); 11. Conflicting accounts flattened (`conflicting_accounts_flattened`). |

## 5. Replace the reported-explanations paragraph

Under `### How these checks should be interpreted`, replace the paragraph starting `**Reported explanations and assessor inferences are different.**` with:

> **Reported explanations and assessor inferences are different.** Reporting that a participant believes one event caused another is different from stating that the causal relationship is established. The tool should preserve that distinction. Presenting the participant's belief as fact is checked under check 14, Opinion as fact. A causal relationship asserted without interview support is checked under check 12, Unsupported causal links.

## 6. Replace the stated-figure paragraph

Under the same heading, replace the paragraph starting `**A stated figure is a claim like any other.**` with:

> **A stated figure is a claim like any other.** The tool compares figures with what the interview gives. It does not judge whether a figure is clinically right, and ordinary rounding is not a discrepancy. A differing stated value is checked under check 13, Quantity mismatch. A total or arithmetic result is checked under check 15, Calculation error, only against figures the supplied interview provides.

## 7. Replace the numerical-score boundary bullet

Under `### No interview administration or protocol review`, replace only the bullet starting `Numerical score calculations:` with:

- Numerical score calculations: scoring rules, rubric totals, and rating arithmetic. Stated interview figures (counts, doses, amounts and other values) are checked under check 13; totals or arithmetic derived from figures the supplied interview gives are checked under check 15. This does not include calculating or validating clinical scores.

## Approval scope

Approval applies to these mission wording changes only: seventeen checks, the narrowed boundaries of checks 6/8/13, new checks 14–17, the four-group mapping, and the explanatory cross-references. Implementation and contract changes remain governed by the approved SP02/SP03 plans. `docs/mission.md` remains unchanged until this wording is approved.
