import { act, renderHook } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { parseInstanceHash, useSelectedInstance } from "./useSelectedInstance";

afterEach(() => {
  window.location.hash = "";
});

describe("instance hash", () => {
  it("parses #i=<id> and ignores anything else", () => {
    expect(parseInstanceHash("#i=abc_1")).toBe("abc_1");
    expect(parseInstanceHash("#i=")).toBeNull();
    expect(parseInstanceHash("#other")).toBeNull();
    expect(parseInstanceHash("")).toBeNull();
    expect(parseInstanceHash("#i=%3Cb%3E")).toBe("<b>");
  });

  it("reads the hash, selects by writing it, and reacts to hashchange", () => {
    window.location.hash = "#i=first";
    const { result } = renderHook(() => useSelectedInstance());
    expect(result.current[0]).toBe("first");
    act(() => result.current[1]("second"));
    expect(window.location.hash).toBe("#i=second");
    act(() => {
      window.location.hash = "";
      window.dispatchEvent(new HashChangeEvent("hashchange"));
    });
    expect(result.current[0]).toBeNull();
  });
});
