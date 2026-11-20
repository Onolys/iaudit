// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { createEvalApi } from "./evalApi";
import { CompareView } from "./CompareView";
import comparison from "./fixtures/comparison.json";
import zero from "./fixtures/comparison-zero-shared.json";

afterEach(cleanup);
const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status });
const deferred = <T,>() => {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>(r => { resolve = r; });
  return { promise, resolve };
};

it("shows run labels, shared count, signed deltas, differing pairs and raw-ID navigation", async () => {
  const fetch = vi.fn<typeof globalThis.fetch>().mockResolvedValue(json(comparison));
  const onOpenItem = vi.fn();
  const onBack = vi.fn();
  render(<CompareView api={createEvalApi({ fetch })} aRunId="run/a" bRunId="run&b" onOpenItem={onOpenItem} onBack={onBack} />);
  await screen.findByText("n shared = 2");
  expect(screen.getByText(`A: ${comparison.run_a}`)).toBeTruthy();
  expect(screen.getByText(`B: ${comparison.run_b}`)).toBeTruthy();
  const metrics = screen.getByRole("table", { name: "Metric deltas" });
  expect(within(metrics).getByText("-0.5")).toBeTruthy();
  expect(within(metrics).getByText("primary")).toBeTruthy();
  const pairs = screen.getByRole("table", { name: "Disagreements for fictional-item-0" });
  expect(within(pairs).getByText("fictional-unit")).toBeTruthy();
  expect(within(pairs).getAllByText("positive")).toHaveLength(2);
  expect(within(pairs).getByText("negative")).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: "open in A" }));
  fireEvent.click(screen.getByRole("button", { name: "open in B" }));
  expect(onOpenItem.mock.calls).toEqual([["run/a", "fictional-item-0"], ["run&b", "fictional-item-0"]]);
  fireEvent.click(screen.getByRole("button", { name: "Back" }));
  expect(onBack).toHaveBeenCalledOnce();
  expect(fetch.mock.calls[0][0]).toBe("/eval-api/compare?a=run%2Fa&b=run%26b");
});

it("only shows delta intervals with ok status and explicitly signs positive/zero deltas", async () => {
  const base = comparison.deltas[0];
  const deltas = [
    { ...base, metric: "positive", delta: 0.1, delta_ci: [-0.1, 0.3], ci_status: "ok" },
    { ...base, metric: "few", delta: 0, delta_ci: [-0.9, 0.9], ci_status: "few_clusters" },
    { ...base, metric: "undefined", delta: null, delta_ci: [-0.8, 0.8], ci_status: "undefined" },
  ];
  const fetch = vi.fn<typeof globalThis.fetch>().mockResolvedValue(json({ ...comparison, deltas }));
  render(<CompareView api={createEvalApi({ fetch })} aRunId="a" bRunId="b" onOpenItem={() => {}} onBack={() => {}} />);
  const table = await screen.findByRole("table", { name: "Metric deltas" });
  expect(within(table).getByText("+0.1")).toBeTruthy();
  expect(within(table).getByText("+0")).toBeTruthy();
  expect(within(table).getByText("[-0.1, +0.3]")).toBeTruthy();
  expect(within(table).getByTitle("few_clusters").textContent).toBe("-");
  expect(within(table).getByTitle("undefined").textContent).toBe("-");
  expect(table.textContent).not.toContain("0.9");
  expect(table.textContent).not.toContain("0.8");
});

it("shows the exact no-shared-items state without tables", async () => {
  const fetch = vi.fn<typeof globalThis.fetch>().mockResolvedValue(json(zero));
  render(<CompareView api={createEvalApi({ fetch })} aRunId="a" bRunId="b" onOpenItem={() => {}} onBack={() => {}} />);
  expect(await screen.findByText("No shared items")).toBeTruthy();
  expect(screen.getByText("n shared = 0")).toBeTruthy();
  expect(screen.queryByRole("table")).toBeNull();
});

it.each([409, 422])("shows cross-dataset HTTP %s inline", async status => {
  const fetch = vi.fn<typeof globalThis.fetch>().mockResolvedValue(json({ error: { code: "invalid_request", message: "Runs use different datasets." } }, status));
  render(<CompareView api={createEvalApi({ fetch })} aRunId="a" bRunId="b" onOpenItem={() => {}} onBack={() => {}} />);
  expect(await screen.findByRole("alert")).toBeTruthy();
  expect(screen.getByText("Runs use different datasets.")).toBeTruthy();
  expect(screen.queryByText("Eval server not reachable")).toBeNull();
});

it("retries an unreachable server with the shared banner", async () => {
  const fetch = vi.fn<typeof globalThis.fetch>().mockRejectedValueOnce(Error("offline")).mockRejectedValueOnce(Error("offline")).mockResolvedValueOnce(json(comparison));
  render(<CompareView api={createEvalApi({ fetch })} aRunId="a" bRunId="b" onOpenItem={() => {}} onBack={() => {}} />);
  await screen.findByText("Eval server not reachable");
  fireEvent.click(screen.getByRole("button", { name: "Retry" }));
  await screen.findByText("n shared = 2");
  expect(screen.queryByRole("alert")).toBeNull();
});

it("ignores old run-pair results and aborts the current request on unmount", async () => {
  const old = deferred<Response>();
  const current = deferred<Response>();
  const fetch = vi.fn<typeof globalThis.fetch>().mockImplementationOnce(() => old.promise).mockResolvedValueOnce(json(zero)).mockImplementationOnce(() => current.promise);
  const realApi = createEvalApi({ fetch });
  const api = { ...realApi, compare: (a: string, b: string) => realApi.compare(a, b) };
  const props = { api, aRunId: "old", bRunId: "b", onOpenItem: () => {}, onBack: () => {} };
  const { rerender, unmount } = render(<CompareView {...props} />);
  rerender(<CompareView {...props} aRunId="new" />);
  await screen.findByText("n shared = 0");
  await act(async () => { old.resolve(json(comparison)); });
  expect(screen.queryByText("n shared = 2")).toBeNull();
  // Restore the real API so unmount reaches its fetch AbortSignal.
  rerender(<CompareView {...props} api={realApi} aRunId="pending" />);
  await waitFor(() => expect(fetch).toHaveBeenCalledTimes(3));
  const signal = fetch.mock.calls[2][1]?.signal;
  unmount();
  expect(signal?.aborted).toBe(true);
  await act(async () => { current.resolve(json(comparison)); });
});
