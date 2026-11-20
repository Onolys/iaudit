import type { ConcernGroup, ConcernType } from "./types";

export const CONCERN_GROUP: Record<ConcernType, ConcernGroup> = {
  unsupported_claim: "not_in_interview",
  unsupported_causal_link: "not_in_interview",
  question_as_answer: "not_in_interview",
  unsupported_inference: "not_in_interview",
  contradictory_evidence: "opposite_of_interview",
  negation_reversal: "opposite_of_interview",
  wrong_attribution: "changed_detail",
  timeframe_mismatch: "changed_detail",
  quantity_mismatch: "changed_detail",
  frequency_severity_inflation: "changed_detail",
  certainty_inflation: "changed_detail",
  opinion_as_fact: "changed_detail",
  calculation_error: "changed_detail",
  meaning_shift: "changed_detail",
  context_stripping: "missing_context",
  correction_ignored: "missing_context",
  conflicting_accounts_flattened: "missing_context",
};

export const CONCERN_GROUP_LABELS: Record<ConcernGroup, string> = {
  not_in_interview: "Not in interview",
  opposite_of_interview: "Opposite of interview",
  changed_detail: "Changed detail",
  missing_context: "Missing context",
};
