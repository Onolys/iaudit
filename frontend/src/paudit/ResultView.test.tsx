// @vitest-environment jsdom
import { cleanup, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import ResultView from "./ResultView";
import sample from "./fixtures/sample-result.json";
import type { PauditResult } from "./types";

afterEach(cleanup);
const result = sample as unknown as PauditResult;

describe("ResultView with the sample result", () => {
  it("lists utterances with code, quote and rationale", () => {
    render(<ResultView result={result} />);
    const table = screen.getByRole("table", { name: "Utterances" });
    const first = result.results[0].instances.find(i => i.code)!;
    const row = within(table).getByText(first.quote).closest("tr")!;
    expect(within(row).getByText(first.code!)).toBeTruthy();
    expect(within(row).getByText(first.rationale)).toBeTruthy();
    expect(within(table).getAllByRole("row").length).toBe(result.results[0].instances.length + 1);
  });

  it("shows counts", () => {
    render(<ResultView result={result} />);
    const table = screen.getByRole("table", { name: "Counts" });
    const sr = within(table).getByText("sr").closest("tr")!;
    expect(within(sr).getByText(String(result.aggregate.counts.sr.mean))).toBeTruthy();
  });

  it("shows summary scores against reference levels", () => {
    render(<ResultView result={result} />);
    const table = screen.getByRole("table", { name: "Summary scores" });
    const tech = within(table).getByText("technical").closest("tr")!;
    expect(within(tech).getByText("4")).toBeTruthy();
    expect(within(tech).getByText("good")).toBeTruthy();
    expect(within(tech).getByText(/fair 3/)).toBeTruthy();
    expect(within(tech).getByText(/good 4/)).toBeTruthy();
    // a summary without reference levels shows a dash for the label
    const mia = within(table).getByText("total_mia").closest("tr")!;
    expect(within(mia).getAllByText("-").length).toBeGreaterThan(0);
  });

  it("shows the four globals with reasons and cited lines", () => {
    render(<ResultView result={result} />);
    const section = screen.getByRole("region", { name: "Global scores" });
    for (const g of ["cct", "sst", "partnership", "empathy"]) expect(within(section).getByText(g)).toBeTruthy();
    const ev = result.results[0].globals.cct.evidence[0];
    expect(within(section).getAllByText(new RegExp(ev.quote.slice(0, 20))).length).toBeGreaterThan(0);
    expect(within(section).getByText(result.results[0].globals.cct.reason)).toBeTruthy();
  });

  it("shows warnings, or says there are none", () => {
    const { rerender } = render(<ResultView result={result} />);
    expect(screen.getByText("No warnings.")).toBeTruthy();
    const warned: PauditResult = {
      ...result,
      warnings: [{ code: "short_session", severity: "warning", item_id: null, detail: "Only 4 minutes coded." }],
    };
    rerender(<ResultView result={warned} />);
    const sec = screen.getByRole("region", { name: "Warnings" });
    expect(within(sec).getByText("short_session")).toBeTruthy();
    expect(within(sec).getByText(/Only 4 minutes coded/)).toBeTruthy();
  });

  it("shows run_info", () => {
    render(<ResultView result={result} />);
    const sec = screen.getByRole("region", { name: "Run info" });
    expect(within(sec).getByText(/^paudit\s/)).toBeTruthy();
    expect(within(sec).getByText(/miti@4\.2\.1/)).toBeTruthy();
    expect(within(sec).getByText(/anthropic\/claude-sonnet-5-5/)).toBeTruthy();
  });
});
