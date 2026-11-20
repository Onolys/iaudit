import { describe, expect, it } from "vitest";
import { buildSegments } from "./spans";

const text = "Hi \u{1F60A} there café now";
// code points: H0 i1 _2 😊3 _4 t5 h6 e7 r8 e9 _10 c11 a12 f13 e14 ́15 _16 n17 o18 w19

describe("buildSegments", () => {
  it("returns one plain segment when there are no spans", () => {
    expect(buildSegments("abc", [])).toEqual({ segments: [{ text: "abc", ids: [] }], rejected: [] });
  });

  it("highlights after an emoji using code-point offsets", () => {
    const { segments, rejected } = buildSegments(text, [{ id: "a", start: 5, end: 10, quote: "there" }]);
    expect(rejected).toEqual([]);
    expect(segments).toEqual([
      { text: "Hi \u{1F60A} ", ids: [] },
      { text: "there", ids: ["a"] },
      { text: " café now", ids: [] },
    ]);
  });

  it("highlights an emoji itself whole", () => {
    const { segments } = buildSegments(text, [{ id: "e", start: 3, end: 4, quote: "\u{1F60A}" }]);
    expect(segments.find((s) => s.ids.includes("e"))?.text).toBe("\u{1F60A}");
  });

  it("keeps a base letter and its combining accent together", () => {
    const { segments, rejected } = buildSegments(text, [{ id: "c", start: 11, end: 16, quote: "café" }]);
    expect(rejected).toEqual([]);
    expect(segments.find((s) => s.ids.includes("c"))?.text).toBe("café");
    expect(segments.map((s) => s.text).join("")).toBe(text);
  });

  it("splits overlapping spans so each segment lists every covering id", () => {
    const { segments } = buildSegments("abcdefgh", [
      { id: "x", start: 1, end: 5, quote: "bcde" },
      { id: "y", start: 3, end: 7, quote: "defg" },
    ]);
    expect(segments).toEqual([
      { text: "a", ids: [] },
      { text: "bc", ids: ["x"] },
      { text: "de", ids: ["x", "y"] },
      { text: "fg", ids: ["y"] },
      { text: "h", ids: [] },
    ]);
  });

  it("rejects a quote that does not match the slice and leaves the text plain", () => {
    const { segments, rejected } = buildSegments("abcdef", [{ id: "m", start: 1, end: 3, quote: "zz" }]);
    expect(segments).toEqual([{ text: "abcdef", ids: [] }]);
    expect(rejected.map((r) => r.id)).toEqual(["m"]);
  });

  it("rejects out-of-range, empty and non-integer spans; keeps the valid one", () => {
    const { segments, rejected } = buildSegments("abcdef", [
      { id: "o", start: 4, end: 9, quote: "ef" },
      { id: "e", start: 2, end: 2, quote: "" },
      { id: "f", start: 0.5, end: 2, quote: "a" },
      { id: "n", start: -1, end: 2, quote: "ab" },
      { id: "ok", start: 0, end: 2, quote: "ab" },
    ]);
    expect(rejected.map((r) => r.id).sort()).toEqual(["e", "f", "n", "o"]);
    expect(segments[0]).toEqual({ text: "ab", ids: ["ok"] });
  });

  it("treats markup as plain text", () => {
    const t = "<b>x</b> &amp;";
    const { segments } = buildSegments(t, [{ id: "h", start: 0, end: 3, quote: "<b>" }]);
    expect(segments.map((s) => s.text).join("")).toBe(t);
  });
});
