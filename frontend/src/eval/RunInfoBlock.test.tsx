// @vitest-environment jsdom
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, expect, it } from "vitest";
import fixture from "./fixtures/run-finished.json";
import type { RunDetail } from "./evalTypes";
import { RunInfoBlock } from "./RunInfoBlock";

afterEach(cleanup);
const run = fixture as RunDetail;

it("renders persisted fingerprint models, shortened prompt hashes and provenance", () => {
  render(<RunInfoBlock run={run} />);
  expect(screen.getByText(/0123456789abcdef0123456789abcdef01234567.*\(dirty\)/)).toBeTruthy();
  expect(screen.getByText("cheap: fixture-cheap")).toBeTruthy();
  expect(screen.getByText("mid: fixture-mid")).toBeTruthy();
  expect(screen.getByText("strong: fixture-strong")).toBeTruthy();
  expect(screen.getByTitle("0123456789abcdef").textContent).toBe("01234567");
  expect(screen.getByText("fictional-mapping-v1")).toBeTruthy();
  expect(screen.getByText("7")).toBeTruthy();
  expect(screen.getByText("contamination: fictional fixture")).toBeTruthy();
  expect(screen.getByText("$0.12")).toBeTruthy();
  expect(screen.getByText("Warning: mixed fingerprint run.")).toBeTruthy();
  expect(screen.getByText("Fictional mixed fingerprint warning.")).toBeTruthy();
  expect(screen.queryByText(/Input tokens/)).toBeNull();
  expect(screen.queryByText(/Test runs are/)).toBeNull();
});

it("uses unknown for absent/null cost, tolerates a missing fingerprint and omits optional tokens", () => {
  const minimal = { ...run, run_info: { concurrency: 1 }, totals: { failures: 0, cost_usd: null } };
  const { rerender } = render(<RunInfoBlock run={minimal} />);
  expect(screen.getAllByText("unknown").length).toBeGreaterThan(0);
  expect(screen.queryByText("Warning: mixed fingerprint run.")).toBeNull();
  rerender(<RunInfoBlock run={{ ...minimal, totals: undefined }} />);
  expect(screen.getAllByText("unknown").length).toBeGreaterThan(0);
  expect(screen.queryByText(/Output tokens/)).toBeNull();
});

it("shows supplied zero token totals and the test-split informational line without actions", () => {
  render(<RunInfoBlock run={{ ...run, split: "test", totals: { ...run.totals, input_tokens: 0, output_tokens: 123 } }} />);
  expect(screen.getByText("Test runs are for reporting, not tuning.")).toBeTruthy();
  expect(screen.getByText("Input tokens: 0")).toBeTruthy();
  expect(screen.getByText("Output tokens: 123")).toBeTruthy();
  expect(screen.queryByRole("button")).toBeNull();
  expect(screen.queryByRole("dialog")).toBeNull();
});

it("formats cost to cents like the runs list", () => {
  render(<RunInfoBlock run={{ ...run, totals: { failures: 0, cost_usd: 0.1234567 } }} />);
  expect(screen.getByText("$0.12")).toBeTruthy();
});
