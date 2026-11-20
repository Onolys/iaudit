import { describe, expect, it } from "vitest";
import { ApiError } from "../../api/errors";
import { buildCard, cardToForm, emptyForm, formatClock, issuesFromApi, localIssues, parseClock, softCount } from "./card";

describe("clock", () => {
  it("parses mm:ss and formats back", () => {
    expect(parseClock("01:05")).toBe(65);
    expect(parseClock("5:07")).toBe(307);
    expect(parseClock("125:00")).toBe(7500);
    expect(parseClock("1:75")).toBeUndefined();
    expect(parseClock("abc")).toBeUndefined();
    expect(parseClock("")).toBeUndefined();
    expect(formatClock(65)).toBe("01:05");
    expect(formatClock(7500)).toBe("125:00");
  });
});

describe("softCount", () => {
  it("warns past the limit, counting code points, and never blocks", () => {
    expect(softCount("abc", 1000)).toEqual({ length: 3, limit: 1000, over: false });
    expect(softCount("x".repeat(1001), 1000)).toMatchObject({ length: 1001, over: true });
    expect(softCount("😀".repeat(1000), 1000)).toMatchObject({ length: 1000, over: false });
  });
});

describe("card <-> form", () => {
  it("round-trips a filled card", () => {
    const f = emptyForm();
    f.changeGoal = "Cut down";
    f.spanFrom = "01:00";
    f.spanTo = "10:00";
    f.globals.cct = { score: "3", reason: "why", exTime: "02:30", exText: "said" };
    f.counts.gi = { count: "4", note: "n" };
    f.notes = "free";
    const card = buildCard(f);
    expect(card).toEqual({
      change_goal: "Cut down",
      coded_span: { from_s: 60, to_s: 600 },
      globals: { cct: { score: 3, reason: "why", example: { at_s: 150, text: "said" } } },
      counts: { gi: { count: 4, note: "n" } },
      notes: "free",
    });
    expect(buildCard(cardToForm(card))).toEqual(card);
  });

  it("a draft omits empty parts; an unrated global with only a reason keeps score null", () => {
    const f = emptyForm();
    f.globals.sst.reason = "r";
    expect(buildCard(f)).toEqual({ change_goal: "", globals: { sst: { score: null, reason: "r" } } });
  });

  it("no-rating cards carry only change goal and span", () => {
    const f = emptyForm();
    f.changeGoal = "g";
    f.spanFrom = "00:10";
    f.spanTo = "00:20";
    f.notes = "ignored";
    expect(buildCard(f, { noRating: true })).toEqual({ change_goal: "g", coded_span: { from_s: 10, to_s: 20 } });
  });

  it("restores from a card the API stored", () => {
    const f = cardToForm({ change_goal: "g", coded_span: { from_s: 5, to_s: 65 }, globals: { empathy: { score: 5 } }, notes: "n" });
    expect(f).toMatchObject({ changeGoal: "g", spanFrom: "00:05", spanTo: "01:05", notes: "n" });
    expect(f.globals.empathy.score).toBe("5");
    expect(f.globals.cct.score).toBe("");
  });
});

describe("localIssues", () => {
  it("requires a change goal", () => {
    expect(localIssues(emptyForm())).toHaveProperty("change_goal");
  });
  it("needs both span ends, in order", () => {
    const f = emptyForm();
    f.changeGoal = "g";
    f.spanFrom = "01:00";
    expect(localIssues(f)).toHaveProperty("coded_span");
    f.spanTo = "00:30";
    expect(localIssues(f)).toHaveProperty("coded_span");
    f.spanTo = "02:00";
    expect(localIssues(f)).toEqual({});
  });
  it("checks example and count formats only when rating", () => {
    const f = emptyForm();
    f.changeGoal = "g";
    f.globals.cct.exTime = "nope";
    f.counts.gi.count = "-2";
    expect(Object.keys(localIssues(f)).sort()).toEqual(["counts.gi.count", "globals.cct.example.at_s"]);
    expect(localIssues(f, { noRating: true })).toEqual({});
  });
});

describe("issuesFromApi", () => {
  it("maps detail paths to per-field messages without echoing server text", () => {
    const err = new ApiError(422, "rating_invalid", [
      { code: "rating_invalid", message: "globals.cct.reason exceeds 1000 characters" },
      { code: "rating_invalid", message: "notes exceeds 3000 characters" },
      { code: "rating_invalid", message: "change_goal is required" },
    ]);
    const issues = issuesFromApi(err);
    expect(issues["globals.cct.reason"]).toMatch(/1,000/);
    expect(issues.notes).toMatch(/3,000/);
    expect(issues.change_goal).toMatch(/required/i);
  });
  it("returns nothing for details it cannot place", () => {
    expect(issuesFromApi(new ApiError(422, "rating_invalid", [{ code: "rating_invalid", message: "The rating card is not valid (shape or length limits)." }]))).toEqual({});
  });
});
