// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { createEvalApi } from "./evalApi";
import { ItemList } from "./ItemList";
import fixture from "./fixtures/items.json";

afterEach(cleanup);
const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status });
const deferred = <T,>() => {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>(r => { resolve = r; });
  return { promise, resolve };
};

it("requests each radio filter once with a high limit and renders rows and match states", async () => {
  const fetch = vi.fn<typeof globalThis.fetch>().mockImplementation(async () => json(fixture));
  render(<ItemList api={createEvalApi({ fetch })} runId="saved/run" onOpenItem={() => {}} />);
  await screen.findByRole("button", { name: "Public contract example" });
  expect(screen.getAllByRole("columnheader").map(cell => cell.textContent)).toEqual(["Item", "Gold", "Ours", "Match", "Status"]);
  expect(screen.getByRole("cell", { name: "Match" }).textContent).toBe("✓");
  expect(screen.getByRole("cell", { name: "Mismatch" }).textContent).toBe("✗");
  expect(screen.getByRole("cell", { name: "Unknown" }).textContent).toBe("-");
  expect(screen.getByText("failed", { selector: ".chip" })).toBeTruthy();
  for (const filter of ["mismatch", "failed"]) {
    fireEvent.click(screen.getByRole("radio", { name: filter }));
    await waitFor(() => expect(screen.queryByText("Loading items…")).toBeNull());
  }
  expect(fetch).toHaveBeenCalledTimes(3);
  for (const [index, filter] of ["all", "mismatch", "failed"].entries()) {
    const url = new URL(String(fetch.mock.calls[index][0]), "http://local");
    expect(url.pathname).toBe("/eval-api/runs/saved%2Frun/items");
    expect(url.searchParams.get("filter")).toBe(filter);
    expect(Number(url.searchParams.get("limit"))).toBeGreaterThanOrEqual(1777);
    expect(url.searchParams.has("offset")).toBe(false);
  }
});

it("opens raw punctuation-containing IDs once through accessible actions or row clicks", async () => {
  const onOpenItem = vi.fn();
  const ids = ["doc.1", "doc-2", "doc--3"];
  const items = ids.map((item_id, index) => ({ ...fixture.items[0], item_id, label: index === 0 ? "Labeled item" : undefined }));
  const fetch = vi.fn<typeof globalThis.fetch>().mockResolvedValue(json({ total: 3, items }));
  render(<ItemList api={createEvalApi({ fetch })} runId="run" onOpenItem={onOpenItem} />);
  for (const [index, id] of ids.entries()) {
    const button = await screen.findByRole("button", { name: index === 0 ? "Labeled item" : id });
    fireEvent.click(index === 1 ? button.closest("tr")! : button);
  }
  expect(onOpenItem.mock.calls).toEqual(ids.map(id => [id]));
});

it("shows the exact empty-filter message", async () => {
  const fetch = vi.fn<typeof globalThis.fetch>().mockResolvedValue(json({ total: 0, items: [] }));
  render(<ItemList api={createEvalApi({ fetch })} runId="run" onOpenItem={() => {}} />);
  expect(await screen.findByText("No items match this filter.")).toBeTruthy();
});

it("keeps prior rows visible and dimmed while a new filter loads", async () => {
  const next = deferred<Response>();
  const fetch = vi.fn<typeof globalThis.fetch>().mockResolvedValueOnce(json(fixture)).mockImplementationOnce(() => next.promise);
  render(<ItemList api={createEvalApi({ fetch })} runId="run" onOpenItem={() => {}} />);
  await screen.findByRole("button", { name: "Public contract example" });
  fireEvent.click(screen.getByRole("radio", { name: "mismatch" }));
  const table = screen.getByRole("table");
  expect(within(table).getByRole("button", { name: "Public contract example" })).toBeTruthy();
  expect(table.getAttribute("aria-busy")).toBe("true");
  expect(table.classList.contains("is-loading")).toBe(true);
  await act(async () => { next.resolve(json({ total: 0, items: [] })); });
  await screen.findByText("No items match this filter.");
  expect(screen.queryByRole("button", { name: "Public contract example" })).toBeNull();
});

it("ignores a stale filter result even if the injected API ignores cancellation", async () => {
  const stale = deferred<Response>();
  const newest = deferred<Response>();
  const fetch = vi.fn<typeof globalThis.fetch>().mockResolvedValueOnce(json(fixture)).mockImplementationOnce(() => stale.promise).mockImplementationOnce(() => newest.promise);
  const realApi = createEvalApi({ fetch });
  const api = { ...realApi, listItems: (id: string, query: Parameters<typeof realApi.listItems>[1]) => realApi.listItems(id, query) };
  render(<ItemList api={api} runId="run" onOpenItem={() => {}} />);
  await screen.findByRole("button", { name: "Public contract example" });
  fireEvent.click(screen.getByRole("radio", { name: "mismatch" }));
  fireEvent.click(screen.getByRole("radio", { name: "failed" }));
  await act(async () => { newest.resolve(json({ total: 1, items: [fixture.items[1]] })); });
  await waitFor(() => expect(screen.queryByRole("button", { name: "Public contract example" })).toBeNull());
  await act(async () => { stale.resolve(json(fixture)); });
  expect(screen.queryByRole("button", { name: "Public contract example" })).toBeNull();
  expect((screen.getByRole("radio", { name: "failed" }) as HTMLInputElement).checked).toBe(true);
  expect(screen.getAllByRole("row")).toHaveLength(2);
});

it("offers Retry on an inline failure and aborts the active request on unmount", async () => {
  const pending = deferred<Response>();
  const fetch = vi.fn<typeof globalThis.fetch>().mockRejectedValueOnce(Error("offline")).mockRejectedValueOnce(Error("offline")).mockImplementationOnce(() => pending.promise);
  const { unmount } = render(<ItemList api={createEvalApi({ fetch })} runId="run" onOpenItem={() => {}} />);
  expect(await screen.findByRole("alert")).toBeTruthy();
  expect(screen.getByText("Eval server not reachable")).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: "Retry" }));
  await waitFor(() => expect(fetch).toHaveBeenCalledTimes(3));
  const signal = fetch.mock.calls[2][1]?.signal;
  expect(signal?.aborted).toBe(false);
  unmount();
  expect(signal?.aborted).toBe(true);
  await act(async () => { pending.resolve(json(fixture)); });
});

it("retries the selected filter and replaces an inline error with rows", async () => {
  const fetch = vi.fn<typeof globalThis.fetch>().mockRejectedValueOnce(Error("offline")).mockRejectedValueOnce(Error("offline")).mockResolvedValueOnce(json(fixture));
  render(<ItemList api={createEvalApi({ fetch })} runId="run" onOpenItem={() => {}} />);
  await screen.findByRole("alert");
  fireEvent.click(screen.getByRole("button", { name: "Retry" }));
  await screen.findByRole("button", { name: "Public contract example" });
  expect(screen.queryByRole("alert")).toBeNull();
  expect(fetch).toHaveBeenCalledTimes(3);
  expect(String(fetch.mock.calls[2][0])).toContain("filter=all");
});

it("says when the server holds more items than were returned", async () => {
  const fetch = vi.fn<typeof globalThis.fetch>().mockImplementation(async () => json({ ...fixture, total: fixture.items.length + 5 }));
  render(<ItemList api={createEvalApi({ fetch })} runId="r" onOpenItem={() => {}} />);
  await screen.findByRole("button", { name: "Public contract example" });
  expect(screen.getByText(`Showing ${fixture.items.length} of ${fixture.items.length + 5} items`)).toBeTruthy();
});

it("shows no truncation note when every item is shown", async () => {
  const fetch = vi.fn<typeof globalThis.fetch>().mockImplementation(async () => json(fixture));
  render(<ItemList api={createEvalApi({ fetch })} runId="r" onOpenItem={() => {}} />);
  await screen.findByRole("button", { name: "Public contract example" });
  expect(screen.queryByText(/Showing \d+ of/)).toBeNull();
});
