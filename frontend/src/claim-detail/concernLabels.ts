import type { ConcernType } from "../contract";

// Mission check names, in CONCERN_TYPES order.
export const CONCERN_LABELS: Record<ConcernType, string> = {
  unsupported_claim: "Claim support",
  contradictory_evidence: "Contradictory evidence",
  wrong_attribution: "Wrong person, source, or entity attribution",
  timeframe_mismatch: "Timeframe mismatch",
  negation_reversal: "Negation reversal",
  certainty_inflation: "Certainty inflation",
  frequency_severity_inflation: "Frequency or severity inflation",
  context_stripping: "Context stripping",
  question_as_answer: "Question mistaken for an answer",
  correction_ignored: "Correction ignored",
  conflicting_accounts_flattened: "Conflicting accounts flattened",
  unsupported_causal_link: "Unsupported causal links",
  quantity_mismatch: "Quantity mismatch",
};

export const concernLabel = (type: string): string =>
  (CONCERN_LABELS as Record<string, string>)[type] ?? type;
