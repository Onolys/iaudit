---
status: done
summary: "NEEDS_CHANGES — 1 must-fix"
date: 2026-10-21
---
# Initial review — Project C

Diff: `f7a4640...01a694b`.
Personas: Bug Hunter, Security, Architect. This artifact records the principal's synthesis of all three independent persona reviews.

## Verdict: NEEDS_CHANGES

| Persona | Verdict | Findings |
|---|---|---|
| Bug Hunter | NEEDS_CHANGES | One P2 must-fix. |
| Security | PASS | No must-fix findings. |
| Architect | PASS | No must-fix findings. |

## Must-fix

### P2 — Balanced accuracy is reported when a required gold class is absent

[Bug Hunter] `eval/datasets/tofueval/metrics.py:48` aliases the core `BalancedAccuracy`; `eval/src/iaudit_eval/metrics/builtins.py:48–52` averages only the gold classes present. C2 requirement R6 requires null balanced accuracy when either class is absent.

A slice containing one gold-inconsistent summary predicted correctly therefore reports `value=1.0`, `n=1` instead of null. The statically traced calculation is `(1/1)/1 = 1.0`. This affects all four aliases: `bacc_sentence`, `bacc_summary`, `bacc_sentence_meta_unresolved`, and `bacc_summary_meta_unresolved`. It also affects secondary-policy results when excluding unresolved units removes the last example of a class.

The evidence path was traced through metadata → scoring groups → policy handling → bootstrap → metric finalization. This finding is based on static review; it does not claim a new runtime reproduction. It is one deduplicated issue across the four aliases.

## Next step

Route to `dev-code` for a targeted fix: add an opt-in `require_all_classes` parameter to the core balanced-accuracy metric and enable it for the four C2 aliases. Preserve existing default behavior for other users of the core metric. Verify absent-class and secondary-exclusion behavior, then rerun review on the follow-up diff.

All 17 Project C implementation tasks remain done. Track the targeted review fix separately; the settled PRD is not reopened. Project D has not started. Owner live checks remain deferred.
