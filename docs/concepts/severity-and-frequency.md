# Severity and frequency

How the audit compares how often or how badly something happened in the assessment and in the interview.

**Audience:** users and contributors.

Amounts become **buckets** on two ordered scales. Frequency: never, rarely, sometimes, often, most, always. Severity: none, mild, moderate, severe, inability. A number ("twice a month") is converted by rate; a word ("most days") is looked up.

The audit compares the claim's bucket with the interview's, in both directions:

- **The claim is stronger** than the interview: `partially_supported` with `frequency_severity_inflation`, and the explanation says the claim **inflates**. A large gap, or an interview that says "never" or "none", is treated as a contradiction instead.
- **The claim is weaker** than the interview: also `partially_supported` with `frequency_severity_inflation`, and the explanation says the claim **understates**. This reuses the existing concern type; the contract has no separate value for it.
- **Equal, or only one step apart on mixed evidence**: no concern. When one side is a number and the other a word and they are adjacent, the audit gives the benefit of the doubt.

**Boundary with other checks.** Only how often, how bad or how long belongs here (`frequency_severity_inflation`). A stated amount, count or dose that does not match is `quantity_mismatch`; a wrong date or time period is `timeframe_mismatch`. "About ten" becoming "exactly ten" is `certainty_inflation`, and a faithful rounding is not a mismatch at all.

A vague quantifier in the claim ("frequently", "at least", "many") is compatible with a higher rate, so it is not reported as an understatement. Words such as "some", "mild" and "a little" are levels, not lower bounds.

When two people give different rates for the same behaviour, the comparison above would miss it if both fall in one bucket ("twice a month" and "once a month"). A separate check flags conflicting accounts when two speakers' weekly rates differ by `IAUDIT_CHECK_RATE_RATIO` or more (see [configuration](../reference/configuration.md)).
