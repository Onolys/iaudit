// @vitest-environment jsdom
import { cleanup, render, screen, within } from "@testing-library/react";
import { afterEach, expect, it } from "vitest";
import fixture from "./fixtures/metrics.json";
import type { MetricsReport } from "./evalTypes";
import { MetricsTable } from "./MetricsTable";
import { toMetricRows } from "./toMetricRows";

afterEach(cleanup);
const report = fixture as MetricsReport;

it("groups in server order and aligns primary and secondary values with reference rows", () => {
  render(<MetricsTable report={report} />);
  expect(screen.getAllByRole("heading").map(node => node.textContent)).toEqual(["item", "All items", "sentence", "source: fictional-small"]);
  const tables = screen.getAllByRole("table");
  const rows = within(tables[0]).getAllByRole("row");
  expect(rows[1].textContent).toContain("accuracy");
  expect(within(rows[1]).getAllByRole("cell").map(node => node.textContent)).toEqual(["0.3333", "3", "-", "0.5", "2", "-"]);
  expect(rows[2].classList.contains("is-reference")).toBe(true);
  expect(rows[2].textContent).toContain("paper-reported, different model & date");
  expect(within(rows[2]).getAllByRole("cell").map(node => node.textContent)).toEqual(["0.75", "-", "-", "-", "-", "-"]);
  expect(rows).toHaveLength(3);
  expect(screen.getByText("Reference caveats").closest("details")?.open).toBe(false);
  expect(screen.getByText(report.reference_caveats[0])).toBeTruthy();
});

it("keeps item failure counts authoritative and shows policy-none rates separately", () => {
  render(<MetricsTable report={{ ...report, items: { selected: 99, scored: 99, failed: 0, not_run: 0 } }} />);
  expect(screen.getByText("Failures: 0 of 99. Primary counts them wrong; secondary excludes them.")).toBeTruthy();
  expect(screen.queryByRole("rowheader", { name: "failure_rate" })).toBeNull();
  expect(screen.queryByRole("rowheader", { name: "coverage" })).toBeNull();
  expect(screen.getByText("item (All items) failure_rate: 0.3333")).toBeTruthy();
  expect(screen.getByText("item (All items) coverage: 0.6667")).toBeTruthy();
});

it("shows cluster counts on hover and unavailable CI statuses as dash hints", () => {
  render(<MetricsTable report={report} />);
  expect(screen.getAllByTitle("few_clusters").every(node => node.textContent === "-")).toBe(true);
  expect(screen.getAllByTitle("undefined").every(node => node.textContent === "-")).toBe(true);
  expect(screen.getAllByTitle("n_clusters: 3").length).toBeGreaterThan(0);
});

it("shows valid intervals and keeps a missing policy as dashes", () => {
  render(<MetricsTable report={{ ...report, references: [], reference_caveats: [], entries: [{ ...report.entries[0], value: 0.7, ci: [0.5, 0.9], ci_status: "ok" }] }} />);
  const cells = within(screen.getAllByRole("row")[1]).getAllByRole("cell");
  expect(cells.map(node => node.textContent)).toEqual(["0.7", "3", "[0.5, 0.9]", "-", "-", "-"]);
  expect(screen.queryByText("Reference caveats")).toBeNull();
});

it("normalizes equivalent slice keys together while preserving first-seen order", () => {
  const primary = { ...report.entries[0], slice: { b: 2, a: 1 } };
  const secondary = { ...report.entries[1], slice: { a: 1, b: 2 } };
  const result = toMetricRows({ ...report, references: [], entries: [primary, secondary] });
  expect(result.groups).toHaveLength(1);
  expect(result.groups[0].rows).toHaveLength(1);
  expect(result.groups[0].rows[0]).toMatchObject({ metric: "accuracy", primary: { value: 0.3333333333333333 }, secondary: { value: 0.5 } });
});

it("never presents sentence-pair failures as item counts", () => {
  const entry = { ...report.entries[0], metric: "failure_rate", policy: "none" as const, level: "sentence", value: 0.5, n: 100 };
  render(<MetricsTable report={{ ...report, entries: [entry] }} />);
  expect(screen.getByText("Failures: 1 of 3. Primary counts them wrong; secondary excludes them.")).toBeTruthy();
  expect(screen.getByText("sentence (All items) failure_rate: 0.5")).toBeTruthy();
  expect(screen.queryByRole("table")).toBeNull();
});

it("keeps evaluator identities distinct when paper references share metric, slice and source", () => {
  const base = report.references[0];
  const references = [
    { ...base, source: "Same paper table", label: "Evaluator A", note: "Model A settings", value: 0.2 },
    { ...base, source: "Same paper table", label: "Evaluator B", note: "Model B settings", value: 0.8 },
  ];
  render(<MetricsTable report={{ ...report, references }} />);
  for (const [index, label] of ["Evaluator A", "Evaluator B"].entries()) {
    const row = screen.getByText(label).closest("tr")!;
    expect(row.textContent).toContain("paper-reported, different model & date");
    expect(within(row).getAllByRole("cell").map(node => node.textContent)).toEqual([index === 0 ? "0.2" : "0.8", "-", "-", "-", "-", "-"]);
    expect(within(row).getByRole("rowheader").title).toContain(references[index].note);
  }
});
