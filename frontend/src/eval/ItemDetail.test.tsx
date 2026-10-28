// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { createEvalApi } from "./evalApi";
import { ItemDetail } from "./ItemDetail";
import { FailedItem } from "./FailedItem";
import ok from "./fixtures/item-ok.json";
import failed from "./fixtures/item-failed.json";
import unmapped from "./fixtures/item-unmapped.json";

afterEach(() => { cleanup(); vi.unstubAllGlobals(); });
const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status });
const deferred = <T,>() => {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>(r => { resolve = r; });
  return { promise, resolve };
};

it("replays a saved item with gold, original review UI, no upload and no audit call", async () => {
  const network = vi.fn(() => { throw Error("No audit calls allowed"); });
  vi.stubGlobal("fetch", network);
  const fetch = vi.fn<typeof globalThis.fetch>().mockResolvedValue(json(ok));
  const onBack = vi.fn();
  const { container } = render(<ItemDetail api={createEvalApi({ fetch })} runId="run/a" itemId="doc.1--a" onBack={onBack} backLabel="Back to comparison" />);
  await screen.findByText("run/a - doc.1--a");
  expect(screen.getByRole("region", { name: "Gold annotations" })).toBeTruthy();
  expect(container.querySelector(".right-pane .cd-root")?.getAttribute("data-claim-id")).toBe("c-supported");
  expect(container.querySelector('input[type="file"]')).toBeNull();
  expect(screen.queryByRole("button", { name: /Upload request/ })).toBeNull();
  expect(screen.queryByText("Mock data")).toBeNull();
  expect(fetch).toHaveBeenCalledTimes(1);
  expect(fetch.mock.calls[0][0]).toBe("/eval-api/runs/run%2Fa/items/doc.1--a");
  expect(network).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", { name: "Back to comparison" }));
  expect(onBack).toHaveBeenCalledOnce();
});

it("shows failure fields and gold without mounting review", async () => {
  const fetch = vi.fn<typeof globalThis.fetch>().mockResolvedValue(json(failed));
  const { container } = render(<ItemDetail api={createEvalApi({ fetch })} runId="r" itemId="failed" onBack={() => {}} backLabel="Back" />);
  await screen.findByText("No response was saved. Resume the run to retry.");
  expect(screen.getByText("503")).toBeTruthy();
  expect(screen.getByText("backend_unreachable")).toBeTruthy();
  expect(screen.getByRole("region", { name: "Gold annotations" })).toBeTruthy();
  expect(container.querySelector(".app-main")).toBeNull();
});

it.each([
  ["stale", { ...ok, response: { ...ok.response, schema_version: "1.0.0" } }, "The service response does not match the audit response schema."],
  ["invalid", { ...ok, response: { ...ok.response, claims: "bad" } }, "The service response does not match the audit response schema."],
])("uses existing ErrorScreen for %s data without choose-file action", async (_label, body, message) => {
  const fetch = vi.fn<typeof globalThis.fetch>().mockResolvedValue(json(body));
  const { container } = render(<ItemDetail api={createEvalApi({ fetch })} runId="r" itemId="i" onBack={() => {}} backLabel="Back" />);
  expect(await screen.findByText(message)).toBeTruthy();
  expect(screen.getByRole("alert")).toBeTruthy();
  expect(screen.queryByRole("button", { name: "Choose another file" })).toBeNull();
  expect(container.querySelector(".app-main")).toBeNull();
});

it("retries a fetch error through the server banner", async () => {
  const fetch = vi.fn<typeof globalThis.fetch>().mockRejectedValueOnce(Error("offline")).mockRejectedValueOnce(Error("offline")).mockResolvedValueOnce(json(ok));
  render(<ItemDetail api={createEvalApi({ fetch })} runId="r" itemId="i" onBack={() => {}} backLabel="Back" />);
  await screen.findByText("Eval server not reachable");
  fireEvent.click(screen.getByRole("button", { name: "Retry" }));
  await screen.findByText("r - i");
  expect(screen.queryByRole("alert")).toBeNull();
});

it("resets selected claim when opening another item", async () => {
  const fetch = vi.fn<typeof globalThis.fetch>().mockImplementation(async () => json(ok));
  const api = createEvalApi({ fetch });
  const props = { api, runId: "r", itemId: "first", onBack: () => {}, backLabel: "Back" };
  const { container, rerender } = render(<ItemDetail {...props} />);
  await screen.findByText("r - first");
  fireEvent.click(container.querySelector('.left-pane [data-claim-id="c-contradicted"]')!);
  expect(container.querySelector(".right-pane .cd-root")?.getAttribute("data-claim-id")).toBe("c-contradicted");
  rerender(<ItemDetail {...props} itemId="second" />);
  await screen.findByText("r - second");
  expect(container.querySelector(".right-pane .cd-root")?.getAttribute("data-claim-id")).toBe("c-supported");
});

it("ignores stale item responses and aborts pending fetch on unmount", async () => {
  const old = deferred<Response>();
  const pending = deferred<Response>();
  const fetch = vi.fn<typeof globalThis.fetch>().mockImplementationOnce(() => old.promise).mockResolvedValueOnce(json(failed)).mockImplementationOnce(() => pending.promise);
  const realApi = createEvalApi({ fetch });
  const api = { ...realApi, getItem: (run: string, item: string) => realApi.getItem(run, item) };
  const props = { api, runId: "r", itemId: "old", onBack: () => {}, backLabel: "Back" };
  const { rerender, unmount } = render(<ItemDetail {...props} />);
  rerender(<ItemDetail {...props} itemId="new" />);
  await screen.findByText("No response was saved. Resume the run to retry.");
  await act(async () => { old.resolve(json(ok)); });
  expect(screen.queryByText("r - old")).toBeNull();
  expect(screen.getByText("No response was saved. Resume the run to retry.")).toBeTruthy();
  rerender(<ItemDetail {...props} api={realApi} itemId="pending" />);
  await waitFor(() => expect(fetch).toHaveBeenCalledTimes(3));
  const signal = fetch.mock.calls[2][1]?.signal;
  unmount();
  expect(signal?.aborted).toBe(true);
  await act(async () => { pending.resolve(json(ok)); });
});

it("handles unmapped detail honestly without asserting a backend failure", async () => {
  const fetch = vi.fn<typeof globalThis.fetch>().mockResolvedValue(json(unmapped));
  render(<ItemDetail api={createEvalApi({ fetch })} runId="r" itemId="u" onBack={() => {}} backLabel="Back" />);
  await screen.findByText("This item could not be mapped for scoring.");
  expect(screen.getByText("No saved audit response is available.")).toBeTruthy();
  expect(screen.queryByText("No response was saved. Resume the run to retry.")).toBeNull();
});

it("caps failure issues at fifty and omits absent optional fields", () => {
  const issues = Array.from({ length: 73 }, (_, index) => ({ path: `/p${index}`, message: `issue${index}` }));
  const { rerender } = render(<FailedItem failure={{ issues }} />);
  expect(screen.getAllByRole("listitem")).toHaveLength(51);
  expect(screen.getByText("/p0: issue0")).toBeTruthy();
  expect(screen.getByText("and 23 more")).toBeTruthy();
  expect(screen.queryByText("HTTP status")).toBeNull();
  expect(screen.queryByText("Error code")).toBeNull();
  rerender(<FailedItem failure={null} />);
  expect(screen.queryByRole("list")).toBeNull();
  expect(screen.getByText("No response was saved. Resume the run to retry.")).toBeTruthy();
});

it("still replays a validated saved response when scoring status is unmapped", async () => {
  const fetch = vi.fn<typeof globalThis.fetch>().mockResolvedValue(json({ ...ok, status: "unmapped" }));
  const { container } = render(<ItemDetail api={createEvalApi({ fetch })} runId="r" itemId="u" onBack={() => {}} backLabel="Back" />);
  await screen.findByText("This item could not be mapped for scoring.");
  expect(container.querySelector(".right-pane .cd-root")?.getAttribute("data-claim-id")).toBe("c-supported");
  expect(screen.queryByText("No saved audit response is available.")).toBeNull();
});
