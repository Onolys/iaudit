# Limits of an audit

What a result does and does not tell you.

**Audience:** users and contributors.

- **No concern does not mean correct.** A claim with no concern was not found to differ from the interview. The audit can miss things. There is no coverage field in the contract, so an omitted concern means "not found", not "checked and clear".
- **Some checks are quick passes.** Context stripping, certainty inflation, correction ignored, conflicting accounts, unsupported causal links and quantity mismatch come from a model's observation with a lower confidence bar, so they can be missed or over-flagged. Frequency, attribution, negation and timeframe are stronger because code does the comparison.
- **`insufficient_evidence` is not "wrong".** The interview simply does not establish the claim. That is different from `contradicted`.
- **Fidelity is to the supplied interview only.** The audit does not verify that what a participant said is true, and the assessor may know things that were not supplied.
- **Wording is a prompt for review.** Explanations point at a possible discrepancy for a human to inspect. They are not allegations.
- **Quality is measured only on a small set.** The evaluation uses one worked example and eight single-fault variants. Results on it are a smoke check, not an estimate for real interviews. See [evaluation](../testing/evaluation.md).
- **A run can be partial.** If time runs out for a section, the reply is `partial` with a warning naming it. If nothing usable finishes, the request fails (503 or 504) rather than returning an empty audit. See [warnings](../reference/warnings.md).
