import { describe, expect, it } from "vitest";
import { DEFAULT_LANGUAGE, LANGUAGES, SP01_GATE, languagesForGate } from "./config";

describe("language list vs the recorded SP01 gate (ADR 0017)", () => {
  it("records the gate as pending, so the PRD default list applies (provisional)", () => {
    expect(SP01_GATE).toEqual({ adr: "0017", status: "pending", autoDiarizationOk: null });
  });

  it("offers exactly the list derived from the recorded gate", () => {
    expect(LANGUAGES.map((l) => l.value)).toEqual(languagesForGate(SP01_GATE).map((l) => l.value));
    expect(LANGUAGES.map((l) => l.value)).toEqual(["auto", "en-US", "en-GB"]);
    expect(DEFAULT_LANGUAGE).toBe("auto");
  });

  it("drops auto and defaults to en-US when the gate shows diarization failed with auto", () => {
    const g = languagesForGate({ adr: "0017", status: "recorded", autoDiarizationOk: false });
    expect(g.map((l) => l.value)).toEqual(["en-US", "en-GB"]);
  });
});
