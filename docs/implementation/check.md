# Check

Stage 3: the verifier observes, code decides. Code: `backend/src/iaudit_backend/check/`.

**Audience:** maintainers and coding agents.

## Code-only checks (`group_a.py`)

Run before the model call. Attribution: whether the claim's reporter matches the speakers of the evidence. Role handling: a turn with no `role` skips the role-dependent checks and is reported for the `ambiguous_speaker` warning. Question as answer: evidence that is only a question.

## The verifier (`verifier.py`)

One mid-tier call per claim that needs one. Output: per evidence item a relation (entails, contradicts, not addresses), polarity, amounts, timeframe, certainty, experiencer and a confidence; flags for the quick-pass checks; judgments on inference steps. Observations below the confidence floors (`check_min_conf_p0`, `check_min_conf_p1`) are dropped and counted. A missing item triggers one retry.

## Deciding (`synth.py`)

`decide` is a pure function from observations to a verdict, concerns and an evidence role per item (the decision table rows D0 to D9). Pieces:

- **Timeframe.** An item from the wrong period is demoted: it no longer supports or contradicts.
- **Amounts (`amounts.py`).** Claim and evidence amounts become buckets and are compared in both directions; the `inflates` or `understates` direction and an escalation to contradiction come from here. Vague lower-bound cues suppress "understates".
- **Quantity mismatch.** The model raises `quantity_mismatch` as a quick-pass flag. Code drops it unless both the claim and a cited item's turn contain a figure (a numeral, or a number word such as "thousands" or "half"; 4-digit years and the pronoun "one" are ignored on the turn side). On the same items it yields to `certainty_inflation`, `correction_ignored`, `conflicting_accounts_flattened` and `timeframe_mismatch`.
- **Conflicting accounts.** Fired by the verifier flag, or in code when two speakers' weekly rates differ by `check_rate_ratio`.
- **Dedup.** One concern per type; a specific concern suppresses a generic one on the same items; conflicting accounts outranks correction ignored outranks contradictory evidence.
- **Explanations** come from `templates.py`, filled with counts and roles, not model text.

Per-claim stall reasons go to `ctx.extras["check_stalls"]` for the orchestrator.
