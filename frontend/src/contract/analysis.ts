import { isSpanValid, itemLengths } from "./spans";
import type { AuditRequest, AuditResponse, Claim, ClaimCheck, Evidence, Verdict } from "./types";
import { VERDICTS } from "./types";

export type VerdictCounts = Record<Verdict, number>;

export interface ResponseAnalysis {
  orderedClaims: Claim[];
  checks: Record<string, ClaimCheck>;
  counts: { overall: VerdictCounts; bySection: Record<number, VerdictCounts> };
}

const zeros = (): VerdictCounts =>
  Object.fromEntries(VERDICTS.map((v) => [v, 0])) as VerdictCounts;

export function analyzeResponse(request: AuditRequest, response: AuditResponse): ResponseAnalysis {
  const sectionLengths = itemLengths(request, "assessment");
  const turnLengths = itemLengths(request, "transcript");

  const checks: Record<string, ClaimCheck> = {};
  const overall = zeros();
  const bySection: Record<number, VerdictCounts> = {};
  request.assessment.forEach((_, i) => (bySection[i] = zeros()));

  for (const claim of response.claims) {
    const claimSpanOk = isSpanValid(claim.span, sectionLengths, true);
    const evidence: Record<string, boolean> = {};
    for (const ev of claim.evidence) evidence[ev.id] = isSpanValid(ev.span, turnLengths, false);
    checks[claim.id] = {
      claimSpanOk,
      evidence,
      spanOutOfRange: !claimSpanOk || Object.values(evidence).some((ok) => !ok),
    };
    overall[claim.verdict]++;
    const section = bySection[claim.span.start.index];
    if (section) section[claim.verdict]++;
  }

  const valid = response.claims.filter((c) => checks[c.id].claimSpanOk);
  const invalid = response.claims.filter((c) => !checks[c.id].claimSpanOk);
  valid.sort(
    (a, b) =>
      a.span.start.index - b.span.start.index ||
      a.span.start.char - b.span.start.char ||
      a.span.end.char - b.span.end.char,
  );
  return { orderedClaims: [...valid, ...invalid], checks, counts: { overall, bySection } };
}

export function claimIdsFor(
  analysis: ResponseAnalysis,
  verdict: Verdict,
  scope: "all" | number,
): string[] {
  return analysis.orderedClaims
    .filter((c) => c.verdict === verdict && (scope === "all" || c.span.start.index === scope))
    .map((c) => c.id);
}

export function notProcessedSections(response: AuditResponse): Set<number> {
  const out = new Set<number>();
  for (const w of response.warnings) {
    if (w.code === "section_not_processed" && w.section_index !== undefined) out.add(w.section_index);
  }
  return out;
}

export function orderEvidence(
  _request: AuditRequest,
  claim: Claim,
  check: ClaimCheck,
): { placed: Evidence[]; unplaceable: Evidence[] } {
  const placed = claim.evidence.filter((e) => check.evidence[e.id] === true);
  const unplaceable = claim.evidence.filter((e) => check.evidence[e.id] !== true);
  placed.sort(
    (a, b) =>
      a.span.start.index - b.span.start.index ||
      a.span.start.char - b.span.start.char ||
      a.span.end.index - b.span.end.index ||
      a.span.end.char - b.span.end.char,
  );
  return { placed, unplaceable };
}
