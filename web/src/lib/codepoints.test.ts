import { describe, expect, it } from "vitest";
import { buildIndexMap, codePointLength, sliceCodePoints } from "./codepoints";

describe("codepoints", () => {
  it("counts code points, not UTF-16 units", () => {
    expect(codePointLength("a\u{1F60A}b")).toBe(3);
    expect("a\u{1F60A}b".length).toBe(4);
  });

  it("index map has n+1 entries mapping code point -> UTF-16 index", () => {
    expect(buildIndexMap("a\u{1F60A}b")).toEqual([0, 1, 3, 4]);
    expect(buildIndexMap("")).toEqual([0]);
  });

  it("slices by code point with end exclusive; combining accents count separately", () => {
    expect(sliceCodePoints("a\u{1F60A}b", 1, 2)).toBe("\u{1F60A}");
    const s = "café!"; // e + combining acute = 2 code points
    expect(codePointLength(s)).toBe(6);
    expect(sliceCodePoints(s, 3, 5)).toBe("é");
  });
});
