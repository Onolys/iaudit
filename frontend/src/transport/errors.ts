import type { AuditRequest, AuditResponse, ResponseAnalysis, ValidationIssue } from "../contract";

export type LoadError =
  | { kind: "invalid_request_file"; reason: "empty" | "not_json" | "schema"; message?: string; issues?: ValidationIssue[] }
  | { kind: "config_missing" }
  | { kind: "mock_no_match"; requestId?: string }
  | { kind: "network"; url: string }
  | { kind: "timeout"; seconds: number }
  | { kind: "cancelled" }
  | { kind: "http_4xx"; status: number; message?: string }
  | { kind: "http_5xx"; status: number; message?: string }
  | {
      kind: "invalid_response";
      reason: "empty" | "not_json" | "not_object" | "schema" | "duplicate_claim_id" | "duplicate_evidence_id";
      message?: string;
      issues?: ValidationIssue[];
      claimId?: string;
      evidenceId?: string;
    }
  | { kind: "request_id_mismatch"; expected: string; received: string | undefined };

export interface LoadResult {
  ok: true;
  request: AuditRequest;
  response: AuditResponse;
  analysis: ResponseAnalysis;
  source: "service" | "mock";
}

export function isRetryable(error: LoadError): boolean {
  switch (error.kind) {
    case "network":
    case "timeout":
    case "cancelled":
    case "http_5xx":
      return true;
    case "http_4xx":
      return error.status === 408 || error.status === 429;
    default:
      return false;
  }
}
