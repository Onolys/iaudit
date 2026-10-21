import { analyzeResponse, validateRequest } from "../contract";
import type { Result } from "../contract";
import type { LoadError, LoadResult } from "../transport/errors";
import { checkAuditResponse } from "../transport/runAudit";

/** Replay an already-parsed saved pair without parsing JSON or contacting a service. */
export function buildLoadResult(request: unknown, response: unknown): Result<LoadResult, LoadError> {
  const checkedRequest = validateRequest(request);
  if (!checkedRequest.ok) {
    return { ok: false, error: { kind: "invalid_request_file", reason: "schema", issues: checkedRequest.error } };
  }
  const checkedResponse = checkAuditResponse(checkedRequest.value, response);
  if (!checkedResponse.ok) return checkedResponse;
  return {
    ok: true,
    value: {
      ok: true,
      request: checkedRequest.value,
      response: checkedResponse.value,
      analysis: analyzeResponse(checkedRequest.value, checkedResponse.value),
      source: "service",
    },
  };
}
