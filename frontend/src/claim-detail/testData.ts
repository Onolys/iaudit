import example from "@contracts/examples/response.json";
import request from "@contracts/examples/request.json";
import { analyzeResponse } from "../contract";
import type { AuditRequest, AuditResponse, Claim, ClaimCheck } from "../contract";

export const exampleRequest = request as AuditRequest;
export const exampleResponse = example as AuditResponse;
const analysis = analyzeResponse(exampleRequest, exampleResponse);

export interface Props {
  claim: Claim;
  request: AuditRequest;
  check: ClaimCheck;
}

/** Props for a claim of the shared contract example. */
export function exampleProps(id: string): Props {
  const claim = exampleResponse.claims.find((c) => c.id === id)!;
  return { claim, request: exampleRequest, check: analysis.checks[id] };
}

/** Props for a hand-built claim over a given request, run through the real analysis. */
export function inlineProps(req: AuditRequest, claim: Claim): Props {
  const a = analyzeResponse(req, { schema_version: "0.0.1", status: "complete", warnings: [], claims: [claim] });
  return { claim, request: req, check: a.checks[claim.id] };
}
