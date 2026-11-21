import { describe, expect, it } from "vitest";
import { diffChip } from "./chips";

const d = (signed: number | null, status: string) =>
  ({ signed, abs: signed === null ? null : Math.abs(signed), direction: null, status }) as never;

describe("diffChip", () => {
  it("says the difference in words and carries the status as text, not colour alone", () => {
    expect(diffChip(d(-2, "differs"))).toEqual({ text: "Onolys -2 (differs)", tone: "differs" });
    expect(diffChip(d(2, "flagged"))).toEqual({ text: "Onolys +2 (flagged)", tone: "flagged" });
    expect(diffChip(d(1, "agree"))).toEqual({ text: "Onolys +1", tone: "agree" });
    expect(diffChip(d(0, "agree"))).toEqual({ text: "Same as you", tone: "agree" });
  });

  it("handles unrated and missing values", () => {
    expect(diffChip(d(null, "not_rated"))).toEqual({ text: "Not rated", tone: "neutral" });
    expect(diffChip(d(null, "no_onolys_value"))).toEqual({ text: "No Onolys value", tone: "neutral" });
    expect(diffChip(undefined)).toEqual({ text: "–", tone: "neutral" });
  });
});
