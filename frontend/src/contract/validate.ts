import Ajv2020 from "ajv/dist/2020";
import type { ErrorObject } from "ajv";
import requestSchema from "@contracts/audit-request.schema.json";
import responseSchema from "@contracts/audit-response.schema.json";
import type { AuditRequest, AuditResponse } from "./types";

export type Result<T, E> = { ok: true; value: T } | { ok: false; error: E };

export interface ValidationIssue {
  path: string;
  message: string;
}

export type ResponseError =
  | { kind: "not_object" }
  | { kind: "wrong_version" }
  | { kind: "schema"; issues: ValidationIssue[] }
  | { kind: "request_id_mismatch"; expected: string; received: string | undefined }
  | { kind: "duplicate_claim_id"; id: string };

const ajv = new Ajv2020({ allErrors: true, allowUnionTypes: true, strictTypes: false });
const checkRequest = ajv.compile(requestSchema);
const checkResponse = ajv.compile(responseSchema);

function issues(errors: ErrorObject[] | null | undefined): ValidationIssue[] {
  return (errors ?? []).map((e) => ({
    path: e.instancePath || "/",
    message: e.message ?? "invalid",
  }));
}

const isObject = (v: unknown): v is Record<string, unknown> =>
  typeof v === "object" && v !== null && !Array.isArray(v);

export function validateRequest(raw: unknown): Result<AuditRequest, ValidationIssue[]> {
  if (checkRequest(raw)) return { ok: true, value: raw as unknown as AuditRequest };
  return { ok: false, error: issues(checkRequest.errors) };
}

export function validateResponse(
  raw: unknown,
  request: AuditRequest,
): Result<AuditResponse, ResponseError> {
  if (!isObject(raw)) return { ok: false, error: { kind: "not_object" } };
  if (raw.schema_version !== "1.0.0") return { ok: false, error: { kind: "wrong_version" } };
  if (!checkResponse(raw)) {
    return { ok: false, error: { kind: "schema", issues: issues(checkResponse.errors) } };
  }
  const response = raw as unknown as AuditResponse;
  if (request.request_id !== undefined && response.request_id !== request.request_id) {
    return {
      ok: false,
      error: {
        kind: "request_id_mismatch",
        expected: request.request_id,
        received: response.request_id,
      },
    };
  }
  const seen = new Set<string>();
  for (const c of response.claims) {
    if (seen.has(c.id)) return { ok: false, error: { kind: "duplicate_claim_id", id: c.id } };
    seen.add(c.id);
  }
  return { ok: true, value: response };
}
