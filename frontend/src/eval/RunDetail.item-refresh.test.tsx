// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { RunDetail } from "./RunDetail";
import { createEvalApi } from "./evalApi";
import finished from "./fixtures/run-finished.json";
import metrics from "./fixtures/metrics.json";
import type { ItemPage, ItemRow, ScoreState } from "./evalTypes";
const tick = async (ms = 0) => { await act(async () => { await vi.advanceTimersByTimeAsync(ms); }); };
beforeEach(() => vi.useFakeTimers());
afterEach(() => { cleanup(); vi.useRealTimers(); });

function setup(initialScore: ScoreState = "pending") {
  let score = initialScore;
  let revision = 0;
  let holdItems = false;
  const pending: { resolve: (response: Response) => void; page: ItemPage }[] = [];
  const raw: ItemRow = { item_id: "present-first", status: "ok", gold: null, pred: null, match: null };
  const original: ItemRow = { ...raw, label: "Original scored item", gold: "consistent", pred: "consistent", match: true };
  const refreshed: ItemRow[] = [
    { ...raw, label: "Scored mismatch", gold: "inconsistent", pred: "consistent", match: false },
    { item_id: "written-later", label: "Added scored item", status: "ok", gold: "consistent", pred: "consistent", match: true },
  ];
  const fetch = vi.fn(async (url: RequestInfo | URL): Promise<Response> => {
    const path = String(url);
    if (path.endsWith("/rescore")) {
      score = "running";
      return Response.json({ ...finished, score_state: score, progress: undefined, run_info: undefined }, { status: 202 });
    }
    if (path.endsWith("/metrics")) return score === "done" ? Response.json(metrics)
      : Response.json({ error: { code: "not_found", message: "Metrics are not available." } }, { status: 404 });
    if (path.includes("/items?")) {
      const filter = new URL(path, "http://offline.invalid").searchParams.get("filter");
      // Match the API's raw-file projection until scoring produces current item_rows.
      const rows = score !== "done" ? [raw] : revision === 0 ? [original] : refreshed;
      const selected = rows.filter(row => filter !== "mismatch" || row.match === false);
      const page = { total: selected.length, items: selected };
      return holdItems ? new Promise(resolve => pending.push({ resolve, page })) : Response.json(page);
    }
    if (path === `/eval-api/runs/${finished.run_id}`) return Response.json({ ...finished, score_state: score });
    throw Error(`Unexpected offline request ${path}`);
  });
  render(<RunDetail api={createEvalApi({ fetch: fetch as typeof globalThis.fetch })} runId={finished.run_id} onBack={() => {}} onOpenItem={() => {}} />);
  return { fetch, complete: () => { score = "done"; revision++; }, hold: () => { holdItems = true; }, release: () => {
    holdItems = false; const entry = pending.shift()!; entry.resolve(Response.json(entry.page));
  } };
}

it("refreshes partial raw rows into scored rows, keeping the old table dimmed while loading", async () => {
  const s = setup(); await tick();
  const rawRow = screen.getByRole("button", { name: "present-first" }).closest("tr")!;
  expect(within(rawRow).getByRole("cell", { name: "Unknown" })).toBeTruthy();
  expect(screen.queryByRole("button", { name: "Added scored item" })).toBeNull();
  s.hold(); s.complete(); await tick(1000);
  expect(screen.getByRole("table", { name: "Run items" }).getAttribute("aria-busy")).toBe("true");
  expect(screen.getByRole("button", { name: "present-first" })).toBeTruthy();
  await act(async () => s.release());
  const scored = screen.getByRole("button", { name: "Scored mismatch" }).closest("tr")!;
  expect(within(scored).getByRole("cell", { name: "Mismatch" })).toBeTruthy();
  expect(within(scored).getByText("inconsistent")).toBeTruthy();
  expect(screen.getByRole("button", { name: "Added scored item" })).toBeTruthy();
});

it("preserves the mismatch filter and replaces its initially empty fallback after scoring", async () => {
  const s = setup(); await tick(); fireEvent.click(screen.getByRole("radio", { name: "mismatch" })); await tick();
  expect(screen.getByText("No items match this filter.")).toBeTruthy();
  s.complete(); await tick(1000);
  expect((screen.getByRole("radio", { name: "mismatch" }) as HTMLInputElement).checked).toBe(true);
  expect(screen.getByRole("button", { name: "Scored mismatch" })).toBeTruthy();
  expect(screen.queryByRole("button", { name: "Added scored item" })).toBeNull();
});

it("refreshes the current mismatch selection again after Re-score completes", async () => {
  const s = setup("done"); await tick(); fireEvent.click(screen.getByRole("radio", { name: "mismatch" })); await tick();
  expect(screen.getByText("No items match this filter.")).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: "Re-score" })); await tick();
  expect(screen.getByText("Scoring...")).toBeTruthy(); s.complete(); await tick(1000);
  expect((screen.getByRole("radio", { name: "mismatch" }) as HTMLInputElement).checked).toBe(true);
  expect(screen.getByRole("button", { name: "Scored mismatch" })).toBeTruthy();
  expect(screen.queryByText("No items match this filter.")).toBeNull();
});

it("refreshes items while a run runs and when it ends", async () => {
  let state = "running", done = 1;
  const fetch = vi.fn(async (url: RequestInfo | URL): Promise<Response> => {
    const path = String(url);
    if (path.endsWith("/metrics")) return Response.json({ error: { code: "not_found", message: "n/a" } }, { status: 404 });
    if (path.includes("/items?")) return Response.json({ total: 0, items: [] });
    return Response.json({ ...finished, state, score_state: state === "running" ? "pending" : "done", progress: { done, total: 3, failures: 0, cost_usd: null } });
  });
  render(<RunDetail api={createEvalApi({ fetch: fetch as typeof globalThis.fetch })} runId={finished.run_id} onBack={() => {}} onOpenItem={() => {}} />);
  const itemCalls = () => fetch.mock.calls.filter(([u]) => String(u).includes("/items?")).length;
  await tick(); const first = itemCalls();
  await tick(1000); expect(itemCalls()).toBe(first);
  done = 2; await tick(1000); expect(itemCalls()).toBe(first + 1);
  state = "finished"; done = 3; await tick(1000); expect(itemCalls()).toBeGreaterThan(first + 1);
});
