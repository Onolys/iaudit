import { describe, expect, it } from "vitest";
import { codePointLength, sliceCodePoints } from "./codepoints";
import { isSpanValid, walkSpan, segmentSection } from "./spans";
import type { AuditRequest, Claim, Span } from "./types";

const request: AuditRequest = {
  schema_version: "1.1.0",
  transcript: [
    { id: "t0", speaker: "a", text: "hello" },
    { id: "t1", speaker: "b", text: "" },
    { id: "t2", speaker: "a", text: "middle" },
    { id: "t3", speaker: "b", text: "world!" },
  ],
  assessment: [
    { id: "s0", text: "abcdefghij" },
    { id: "s1", text: "klm" },
  ],
};
const sp = (si: number, sc: number, ei: number, ec: number): Span => ({
  start: { index: si, char: sc },
  end: { index: ei, char: ec },
});
const claims = (src: "assessment" | "transcript") => (src === "assessment" ? request.assessment : request.transcript);

describe("codepoints", () => {
  it("length and slice by code point, end exclusive", () => {
    expect(codePointLength("héllo")).toBe(5);
    expect(sliceCodePoints("abcdef", 1, 3)).toBe("bc");
    expect(sliceCodePoints("a😀b", 1, 2)).toBe("😀");
  });
});

describe("isSpanValid (R3)", () => {
  const ok = (s: Span, src: "assessment" | "transcript") =>
    isSpanValid(s, claims(src).map((i) => codePointLength(i.text)), src === "assessment");
  it("passes a normal claim span", () => expect(ok(sp(0, 0, 0, 5), "assessment")).toBe(true));
  it("end.char === len is ok", () => expect(ok(sp(0, 0, 0, 10), "assessment")).toBe(true));
  it("end.char > len fails", () => expect(ok(sp(0, 0, 0, 11), "assessment")).toBe(false));
  it("start.char === len fails", () => expect(ok(sp(0, 5, 2, 3), "transcript")).toBe(false));
  it("empty span fails (strict order)", () => expect(ok(sp(0, 3, 0, 3), "assessment")).toBe(false));
  it("reversed fails", () => expect(ok(sp(0, 5, 0, 2), "assessment")).toBe(false));
  it("index out of range fails", () => expect(ok(sp(0, 0, 2, 1), "assessment")).toBe(false));
  it("negative or fractional fails", () => {
    expect(ok(sp(0, -1, 0, 2), "assessment")).toBe(false);
    expect(ok(sp(0, 0, 0, 1.5), "assessment")).toBe(false);
  });
  it("claim must stay in one section", () => expect(ok(sp(0, 0, 1, 2), "assessment")).toBe(false));
  it("evidence may cross turns", () => expect(ok(sp(0, 1, 2, 3), "transcript")).toBe(true));
  it("empty-turn start fails", () => expect(ok(sp(1, 0, 2, 3), "transcript")).toBe(false));
  it("start index after end index fails", () => expect(ok(sp(2, 0, 0, 3), "transcript")).toBe(false));
});

describe("walkSpan", () => {
  it("single item gives one segment", () => {
    expect(walkSpan(request, sp(0, 1, 0, 4), "assessment")).toEqual([
      { index: 0, from: 1, to: 4, length: 10, text: "bcd" },
    ]);
  });
  it("cross-turn includes empty middle turn", () => {
    expect(walkSpan(request, sp(0, 3, 3, 2), "transcript")).toEqual([
      { index: 0, from: 3, to: 5, length: 5, text: "lo" },
      { index: 1, from: 0, to: 0, length: 0, text: "" },
      { index: 2, from: 0, to: 6, length: 6, text: "middle" },
      { index: 3, from: 0, to: 2, length: 6, text: "wo" },
    ]);
  });
  it("throws RangeError on invalid span", () => {
    expect(() => walkSpan(request, sp(0, 0, 0, 99), "assessment")).toThrow(RangeError);
  });
});

describe("segmentSection", () => {
  const claim = (id: string, s: Span): Claim => ({
    id, span: s, verdict: "supported", explanation: "x", concerns: [], evidence: [],
  });
  const check = (ok: boolean) => ({ spanOutOfRange: !ok, claimSpanOk: ok, overlapsEarlier: false, evidence: {} });
  it("partitions into plain gaps and claims", () => {
    const cs = [claim("a", sp(0, 2, 0, 4)), claim("b", sp(0, 6, 0, 10))];
    const pieces = segmentSection(request, 0, { a: check(true), b: check(true) }, cs);
    expect(pieces).toEqual([
      { kind: "plain", from: 0, to: 2, text: "ab" },
      { kind: "claim", from: 2, to: 4, text: "cd", claimId: "a" },
      { kind: "plain", from: 4, to: 6, text: "ef" },
      { kind: "claim", from: 6, to: 10, text: "ghij", claimId: "b" },
    ]);
  });
  it("skips invalid claims and other sections", () => {
    const cs = [claim("a", sp(0, 2, 0, 4)), claim("z", sp(1, 0, 1, 2))];
    const pieces = segmentSection(request, 0, { a: check(false), z: check(true) }, cs);
    expect(pieces).toEqual([{ kind: "plain", from: 0, to: 10, text: "abcdefghij" }]);
  });
  it("renders an overlapping claim as plain, no duplicate text", () => {
    const cs = [claim("a", sp(0, 0, 0, 6)), claim("b", sp(0, 4, 0, 8))];
    const pieces = segmentSection(request, 0, { a: check(true), b: check(true) }, cs);
    expect(pieces.map((p) => p.text).join("")).toBe("abcdefghij");
    expect(pieces.filter((p) => p.kind === "claim").map((p) => p.claimId)).toEqual(["a"]);
  });
});
