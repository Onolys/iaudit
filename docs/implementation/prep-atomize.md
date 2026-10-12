# Prep and atomize

Stages 0 and 1. Code: `backend/src/iaudit_backend/prep/` and `atomize/`.

**Audience:** maintainers and coding agents.

## Prep

`prep(turns, ctx)` returns indexed turns and question-answer pairs.

- **Acts.** `rules.py` tags each turn with dialogue acts (question, answer, backchannel, hypothetical, correction) by rules only. A rule says yes, no or unsure. Unsure resolves to no act.
- **Pairing.** `pairing.py` links each question to the replies that follow it, using `speaker` strings only, so it works without roles. A reply gets `responds_to`.
- **Optional model tagging.** With `prep_llm`, the unsure turns go to a cheap-tier call in chunks (`prompt.py`, `llm.py`). The model may only add the kinds that were unsure for that turn. A bad chunk keeps the rule result and counts in `degraded_chunks`. After merging, the answer and backchannel acts are re-derived from the merged question set, then pairing runs.
- **Rules-only path.** `prep_rules_only` makes no model call; the flow uses it when prep passes its soft timeout.

## Atomize

`atomize_section` makes one mid-tier call per section. The input is the section text and a roster of speakers (no transcript text). The model returns claims with verbatim segments, a self-contained proposition, scope, reporters, polarity, quantities, timeframe and hedging.

Code then validates (`validate.py`): each segment must be found in the section, claims are capped, quantities are mapped to buckets by `scales.py`, and out-of-scope claims get a fixed reason sentence by category. The model never writes the contract's out-of-scope reason. An invalid answer is retried once. Claims carry a `span_hint` (code points) that the assembler re-verifies.

The prompt prefix (system, taxonomy, few-shot) is stable and cacheable. Few-shot examples are fictional and are checked against evaluation data for overlap.
