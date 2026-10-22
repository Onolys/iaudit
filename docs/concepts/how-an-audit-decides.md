# How an audit decides

How the backend turns an assessment and an interview into a verdict per claim.

**Audience:** users and contributors.

## From text to claims

The backend splits each assessment section into **claims**: short statements the interview can support or contradict. A claim that needs outside criteria or unseen observations (a diagnosis, a score rule, a recommendation) is marked **out of scope** and is not forced into a factual verdict. The thirteen checks and the four verdicts are defined in the [mission](../mission.md).

## Evidence

For each in-scope claim, a model proposes **evidence**: excerpts from the interview that bear on it, each with a role (supporting, contradicting, or qualifying). The reviewer sees a highlight at a position in the interview, never a copied quote. Positions are computed by code from the model's excerpt, so the model cannot invent a location.

## The model observes, code decides

A second model call reports **observations** about each piece of evidence: does it say the same thing, the opposite, or nothing relevant; was it about the claim's subject; how often, how severe, when, how sure. It does not pick the verdict and writes no explanation.

Code then decides, from those observations, in a fixed order:

1. No evidence at all gives `insufficient_evidence`.
2. Contradicting evidence and no support gives `contradicted`.
3. Contradicting evidence next to support gives `partially_supported`.
4. No support and no contradiction gives `insufficient_evidence`.
5. Support with concerns (an exaggerated amount, a changed time, a missing qualification) gives `partially_supported`.
6. Support with nothing wrong gives `supported`.

Concerns are then de-duplicated so one problem is explained once, with the most specific concern kept. Explanations are written from fixed templates filled with counts and roles, not free text.

## Quantity mismatch

Check 13 (`quantity_mismatch`) covers amounts, counts, doses, ages, tallies and sums that the assessment states about the interview ("took 10 mg" when the interview says 20 mg; "three missed appointments" when the interview gives two). Dates and timing stay under `timeframe_mismatch`; how often, how bad or how long stays under `frequency_severity_inflation`. A faithful rounding ("about ten" for 9 or 11) is not a mismatch, while turning "about ten" into "exactly ten" is `certainty_inflation`.

## Labelling rules for close calls

- **Changed action.** When the assessment changes what someone did, the concern is `contradictory_evidence` if the interview states the actual action, otherwise `unsupported_claim`.
- **Two true facts joined.** When two facts that are each true are merged into a relation the interview never states, the concern is `unsupported_claim`. It is `unsupported_causal_link` only when the assessment asserts cause and effect.
- **Wrong attribution** covers the wrong person, source or entity: who experienced or reported something, and which person, source or entity a fact belongs to (for example a side effect attributed to the wrong medication).
- **Context stripping** covers an omitted qualification and also a broadened scope ("some members" becomes "the panel").

## What a reviewer should read into a result

Every result is a prompt for human review, not an allegation. See [limits of an audit](limits-of-an-audit.md). How amounts are compared: [severity and frequency](severity-and-frequency.md).
