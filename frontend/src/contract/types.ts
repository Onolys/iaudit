import type { EvidenceRole, Verdict } from "../tokens";

export type { EvidenceRole, Verdict };

export const SCHEMA_VERSION = "0.0.1" as const;

export const VERDICTS = [
  "supported",
  "partially_supported",
  "contradicted",
  "insufficient_evidence",
  "out_of_scope",
] as const;

// Mission checks 1-13, in order.
export const CONCERN_TYPES = [
  "unsupported_claim",
  "contradictory_evidence",
  "wrong_attribution",
  "timeframe_mismatch",
  "negation_reversal",
  "certainty_inflation",
  "frequency_severity_inflation",
  "context_stripping",
  "question_as_answer",
  "correction_ignored",
  "conflicting_accounts_flattened",
  "unsupported_causal_link",
  "quantity_mismatch",
] as const;

export const EVIDENCE_ROLES = ["supporting", "contradicting", "qualifying"] as const;

export const WARNING_CODES = [
  "section_not_processed",
  "span_out_of_range",
  "ambiguous_speaker",
  "input_truncated",
  "other",
] as const;

export const STATUSES = ["complete", "partial"] as const;

export type ConcernType = (typeof CONCERN_TYPES)[number];
export type WarningCode = (typeof WARNING_CODES)[number];
export type Status = (typeof STATUSES)[number];

export interface Turn {
  id: string;
  speaker: string;
  role?: "interviewer" | "respondent" | "informant" | "other";
  text: string;
  timestamp?: string;
}

export interface Section {
  id: string;
  label?: string;
  score?: number | string;
  text: string;
}

export interface AuditRequest {
  schema_version: typeof SCHEMA_VERSION;
  request_id?: string;
  transcript: Turn[];
  assessment: Section[];
}

export interface Pointer {
  index: number;
  char: number;
}

export interface Span {
  start: Pointer;
  end: Pointer;
}

export interface Evidence {
  id: string;
  role: EvidenceRole;
  span: Span;
  note?: string;
}

export interface Concern {
  type: ConcernType;
  explanation: string;
  evidence_ids: string[];
}

export interface Warning {
  code: WarningCode;
  message: string;
  claim_id?: string;
  section_index?: number;
}

export interface Claim {
  id: string;
  span: Span;
  verdict: Verdict;
  explanation: string;
  out_of_scope_reason?: string;
  suggested_revision?: string | null;
  concerns: Concern[];
  evidence: Evidence[];
}

export interface RunInfo {
  models: { cheap: string; mid: string; strong: string };
  /** 16 lowercase hex chars each */
  prompt_hashes: { atomize: string; link: string; check: string; prep: string };
  input_tokens?: number;
  output_tokens?: number;
  cache_read_tokens?: number;
  cache_write_tokens?: number;
  cost_usd?: number;
}

export interface AuditResponse {
  schema_version: typeof SCHEMA_VERSION;
  request_id?: string;
  status: Status;
  warnings: Warning[];
  claims: Claim[];
  run_info?: RunInfo;
}

export interface ClaimCheck {
  spanOutOfRange: boolean;
  claimSpanOk: boolean;
  /** true = in range but overlaps an earlier claim, so it cannot be highlighted */
  overlapsEarlier: boolean;
  /** key = Evidence.id; true = placeable */
  evidence: Record<string, boolean>;
}
