import { describe, expect, it } from "vitest";
import requestExample from "@contracts/examples/request.json";
import responseExample from "@contracts/examples/response.json";
import { analyzeResponse, claimIdsFor, notProcessedSections, orderEvidence } from "./analysis";
import type { AuditRequest, AuditResponse, Claim, Span } from "./types";

const req = () => structuredClone(requestExample) as unknown as AuditRequest;
const res = () => structuredClone(responseExample) as unknown as AuditResponse;
const sp = (si: number, sc: number, ei: number, ec: number): Span => ({
  start: { index: si, char: sc },
  end: { index: ei, char: ec },
});

describe("analyzeResponse on the example pair", () => {
  const a = analyzeResponse(req(), res());
  it("has 5 claims, no flags, counts 1 each", () => {
    expect(a.orderedClaims).toHaveLength(5);
    expect(Object.values(a.checks).every((c) => !c.spanOutOfRange)).toBe(true);
    expect(Object.values(a.counts.overall)).toEqual([1, 1, 1, 1, 1]);
    expect(a.counts.bySection[0].supported).toBe(1);
  });
  it("orders in text order", () => {
    expect(a.orderedClaims.map((c) => c.id)).toEqual([
      "c-supported", "c-contradicted", "c-partial", "c-insufficient", "c-oos",
    ]);
  });
  it("claimIdsFor filters by verdict and scope", () => {
    expect(claimIdsFor(a, "contradicted", "all")).toEqual(["c-contradicted"]);
    expect(claimIdsFor(a, "contradicted", 0)).toEqual(["c-contradicted"]);
    expect(claimIdsFor(a, "contradicted", 1)).toEqual([]);
  });
});

describe("flags", () => {
  it("bad claim span flags only that claim", () => {
    const r = res();
    r.claims[1].span = sp(0, 0, 0, 9999);
    const a = analyzeResponse(req(), r);
    expect(a.checks["c-contradicted"]).toMatchObject({ spanOutOfRange: true, claimSpanOk: false });
    expect(a.checks["c-supported"].spanOutOfRange).toBe(false);
    expect(a.counts.overall.contradicted).toBe(1);
    expect(a.orderedClaims.at(-1)!.id).toBe("c-contradicted");
  });
  it("bad evidence span flags only that claim", () => {
    const r = res();
    r.claims[0].evidence[1].span = sp(5, 0, 5, 9999);
    const a = analyzeResponse(req(), r);
    expect(a.checks["c-supported"]).toMatchObject({
      spanOutOfRange: true,
      claimSpanOk: true,
      evidence: { "e-caregiver": true, "e-illness": false },
    });
    expect(a.checks["c-contradicted"].spanOutOfRange).toBe(false);
  });
  it("claim in unknown section counts in overall only", () => {
    const r = res();
    r.claims[0].span = sp(7, 0, 7, 3);
    const a = analyzeResponse(req(), r);
    expect(a.counts.overall.supported).toBe(1);
    expect(a.counts.bySection[0].supported).toBe(0);
  });
});

describe("ordering", () => {
  it("sorts out-of-order claims; invalid last in response order", () => {
    const r = res();
    const [s, c, p, i, o] = r.claims;
    i.span = sp(0, 0, 0, 9999);
    s.span = sp(0, 0, 0, 9998);
    r.claims = [o, i, p, s, c];
    const a = analyzeResponse(req(), r);
    expect(a.orderedClaims.map((x) => x.id)).toEqual([
      "c-contradicted", "c-partial", "c-oos", "c-insufficient", "c-supported",
    ]);
  });
});

describe("notProcessedSections", () => {
  it("collects section indexes from warnings", () => {
    const r = res();
    r.warnings = [
      { code: "section_not_processed", message: "m", section_index: 2 },
      { code: "other", message: "m", section_index: 5 },
    ];
    expect(notProcessedSections(r)).toEqual(new Set([2]));
  });
});

describe("orderEvidence", () => {
  it("sorts placed, splits unplaceable", () => {
    const claim = {
      evidence: [
        { id: "b", role: "supporting", span: sp(3, 0, 3, 2) },
        { id: "x", role: "qualifying", span: sp(9, 0, 9, 2) },
        { id: "a", role: "supporting", span: sp(1, 4, 1, 6) },
      ],
    } as unknown as Claim;
    const out = orderEvidence(req(), claim, {
      spanOutOfRange: true, claimSpanOk: true, evidence: { a: true, b: true, x: false },
    });
    expect(out.placed.map((e) => e.id)).toEqual(["a", "b"]);
    expect(out.unplaceable.map((e) => e.id)).toEqual(["x"]);
  });
});
