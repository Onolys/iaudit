import { describe, expect, it } from "vitest";
import { analyzeResponse } from "../contract";
import type { AuditRequest, AuditResponse, Claim } from "../contract";
import { initialState, reviewReducer } from "./reviewState";

const request: AuditRequest = {
  schema_version: "1.0.0",
  transcript: [{ id: "t0", speaker: "A", text: "hello world" }],
  assessment: [
    { id: "s0", text: "aaaa bbbb cccc" },
    { id: "s1", text: "dddd eeee" },
  ],
};

const claim = (id: string, verdict: Claim["verdict"], index: number, start: number): Claim => ({
  id,
  verdict,
  explanation: "x",
  concerns: [],
  evidence: [],
  span: { start: { index, char: start }, end: { index, char: start + 2 } },
});

const response: AuditResponse = {
  schema_version: "1.0.0",
  status: "complete",
  warnings: [],
  claims: [
    claim("c1", "supported", 0, 0),
    claim("c2", "contradicted", 0, 5),
    claim("c3", "supported", 0, 10),
    claim("c4", "supported", 1, 0),
  ],
};
const analysis = analyzeResponse(request, response);

describe("reviewReducer", () => {
  it("init selects the first claim in document order, no nav", () => {
    expect(initialState(analysis)).toEqual({ selectedClaimId: "c1", nav: null });
  });

  it("init with no claims selects nothing", () => {
    const empty = analyzeResponse(request, { ...response, claims: [] });
    expect(initialState(empty)).toEqual({ selectedClaimId: null, nav: null });
  });

  it("navigate selects the first claim of the list", () => {
    const s = reviewReducer(initialState(analysis), { type: "navigate", analysis, verdict: "supported", scope: "all" });
    expect(s.selectedClaimId).toBe("c1");
    expect(s.nav).toEqual({ verdict: "supported", scope: "all", claimIds: ["c1", "c3", "c4"], position: 0 });
  });

  it("navigate with a section scope narrows the list", () => {
    const s = reviewReducer(initialState(analysis), { type: "navigate", analysis, verdict: "supported", scope: 1 });
    expect(s.nav?.claimIds).toEqual(["c4"]);
    expect(s.selectedClaimId).toBe("c4");
  });

  it("navigate to an empty list is a no-op", () => {
    const start = initialState(analysis);
    const s = reviewReducer(start, { type: "navigate", analysis, verdict: "out_of_scope", scope: "all" });
    expect(s).toBe(start);
  });

  const navigated = () => reviewReducer(initialState(analysis), { type: "navigate", analysis, verdict: "supported", scope: "all" });

  it("selecting a claim inside the active list keeps nav and moves position", () => {
    const s = reviewReducer(navigated(), { type: "selectClaim", id: "c4" });
    expect(s.selectedClaimId).toBe("c4");
    expect(s.nav?.position).toBe(2);
  });

  it("selecting a claim outside the active list clears nav", () => {
    const s = reviewReducer(navigated(), { type: "selectClaim", id: "c2" });
    expect(s).toEqual({ selectedClaimId: "c2", nav: null });
  });

  it("step moves within the list and selects the claim", () => {
    const s = reviewReducer(navigated(), { type: "step", delta: 1 });
    expect(s.selectedClaimId).toBe("c3");
    expect(s.nav?.position).toBe(1);
  });

  it("step clamps at both ends", () => {
    const first = reviewReducer(navigated(), { type: "step", delta: -1 });
    expect(first.nav?.position).toBe(0);
    let s = navigated();
    for (let i = 0; i < 5; i++) s = reviewReducer(s, { type: "step", delta: 1 });
    expect(s.nav?.position).toBe(2);
    expect(s.selectedClaimId).toBe("c4");
  });

  it("step without nav is a no-op", () => {
    const start = initialState(analysis);
    expect(reviewReducer(start, { type: "step", delta: 1 })).toBe(start);
  });
});
