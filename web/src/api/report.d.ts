/**
 * HAND-WRITTEN stand-in for `json-schema-to-typescript` output of
 * `engines/evaluation/schemas/report.schema.json` (SP03 R7, schema_version
 * "0.0.1"). SP05 T13 replaces this with generated types.
 */

export type DiffStatus = "agree" | "differs" | "flagged" | "not_rated" | "no_onolys_value";
export type ClaimVerdict =
  | "supported"
  | "partially_supported"
  | "contradicted"
  | "insufficient_evidence"
  | "out_of_scope";
export type EvidenceRole = "supporting" | "contradicting" | "qualifying";
export type ReasonsAuditStatus = "ran" | "partial" | "skipped" | "failed";

export interface Diff {
  signed: number | null;
  abs: number | null;
  direction: string | null;
  status: DiffStatus;
  within_one?: boolean | null;
}

/** Code-point offsets into the turn's text. */
export interface Line {
  turn_id: string;
  start: number;
  end: number;
  quote: string;
}

export interface Explanation {
  headline: string;
  body: string[];
  onolys_lines: Line[];
  clinician_support_lines: Line[];
}

export interface RunStats {
  mean: number | null;
  min: number | null;
  max: number | null;
  values: number[];
}

export interface Instance extends Line {
  id: string;
  rationale: string;
}

export interface Claim {
  span: string;
  verdict: ClaimVerdict;
  explanation: string;
  concerns: string[];
  evidence: ({ role: EvidenceRole } & Line)[];
}

export interface Report {
  schema_version: string;
  request_id?: string;
  created_at: string;
  header: {
    change_goal: string;
    protocol: { id: string; version: string; pack_hash: string; label: string };
    language: string;
    coded_span: { from_s: number | null; to_s: number | null } | null;
    subject_speaker: string;
    n_runs: number;
    models: { [route: string]: string };
    stt: {
      provider: string;
      model: string;
      location: string;
      language_requested: string;
      language_detected: string;
      adapter_version: string;
    };
    preset: string;
    code_version: string;
    params: { [key: string]: unknown };
    has_clinician_rating: boolean;
    rating_coverage: { rated: number; total: number };
  };
  layout: { section: string; title: string; items?: string[] }[];
  scorecard: {
    item_id: string;
    kind: "global" | "count";
    label: string;
    clinician: { value: number | null };
    onolys: RunStats & { value: number | null };
    diff: Diff;
  }[];
  globals: {
    item_id: string;
    onolys: { score: number | null; source: string; reason?: string; evidence: Line[] };
    clinician: {
      value: number | null;
      reason?: string;
      example?: { at_s?: number | null; text: string };
    };
    diff: Diff;
    explanation: Explanation;
  }[];
  behaviours: {
    item_id: string;
    clinician_count: number | null;
    clinician_note?: string;
    onolys_count: RunStats;
    instances: Instance[];
    instances_total: number;
    diff: Diff;
    explanation: Explanation;
  }[];
  summaries: {
    id: string;
    label: string;
    clinician: { value: number | null; label: string } | null;
    onolys: { value: number | null; label: string };
    reference: { fair: number; good: number };
    note: string;
  }[];
  reasons_audit: {
    status: ReasonsAuditStatus;
    items: { item_id: string; reason: string; claims: Claim[] }[];
  };
  tips: {
    rank: number;
    item_id: string;
    observation: string;
    quote: { turn_id: string; start: number; end: number; text: string };
    alternative: string;
    why_it_matters: string;
  }[];
  method: {
    statement: string;
    limits: string[];
    not_official_miti_coding: true;
    citation: string;
  };
  aggregates: {
    globals_compared: number;
    avg_abs_global_difference: number | null;
    within_one_share: number | null;
    counts_flagged: number | null;
  };
  warnings: { code: string; item_id?: string }[];
  run_info: { evaluation: unknown; paudit: unknown; eaudit: unknown };
}
