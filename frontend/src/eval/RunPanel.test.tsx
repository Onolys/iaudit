// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { RunPanel } from "./RunPanel";
import { createEvalApi } from "./evalApi";
import datasets from "./fixtures/datasets.json";
import metadata from "./fixtures/dataset-detail.json";
import known from "./fixtures/estimate-known.json";
import unknown from "./fixtures/estimate-unknown.json";
import type { Estimate, RunRequest } from "./evalTypes";
const tick = async (ms = 400) => { await act(async () => { await vi.advanceTimersByTimeAsync(ms); }); };
function setup(empty = false, initial: Estimate = known as Estimate) {
  let estimate = initial;
  const requests: RunRequest[] = [];
  const api = createEvalApi({ fetch: (async (url, init) => {
    if (url === "/eval-api/datasets") return Response.json(empty ? [] : datasets);
    if (String(url).startsWith("/eval-api/datasets/")) return Response.json({ ...metadata, name: String(url).split("/").at(-1) });
    if (url === "/eval-api/runs/estimate") { requests.push(JSON.parse(String(init?.body))); return Response.json(estimate); }
    throw new Error(`Unexpected offline request ${url}`);
  }) as typeof fetch });
  const onRun = vi.fn();
  return { ...render(<RunPanel api={api} onRun={onRun} />), requests, onRun, setEstimate: (next: Estimate) => { estimate = next; } };
}
const input = (name: string) => screen.getByRole("textbox", { name }) as HTMLInputElement;
const run = () => screen.getByRole("button", { name: "Run" }) as HTMLButtonElement;
beforeEach(() => { localStorage.clear(); vi.useFakeTimers(); });
afterEach(() => { cleanup(); vi.useRealTimers(); vi.restoreAllMocks(); });
describe("RunPanel form", () => {
  it("groups datasets by product and retains flat stored ids", async () => {
    const api = createEvalApi({ fetch: (async url => {
      if (url === "/eval-api/datasets") return Response.json([
        { ...datasets[0], product: "eaudit" }, { ...datasets[1], product: "paudit" },
      ]);
      return Response.json(metadata);
    }) as typeof fetch });
    render(<RunPanel api={api} />); await tick(0);
    expect(screen.getByRole("group", { name: "eaudit" }).querySelector("option")?.value).toBe("fictional-alpha");
    expect(screen.getByRole("group", { name: "paudit" }).querySelector("option")?.value).toBe("fictional-beta");
    fireEvent.change(screen.getByLabelText("Dataset"), { target: { value: "fictional-beta" } }); await tick(0);
    expect(localStorage.getItem("iaudit.eval.dataset")).toBe("fictional-beta");
  });
  it("debounces whole-split cost and submits blank cap as omitted", async () => {
    const { requests, onRun } = setup(); await tick(0); await tick(399); expect(requests).toEqual([]); await tick(1);
    expect(requests).toEqual([{ dataset: "fictional-alpha", split: "validation" }]);
    expect(screen.getByText("~$0.12 for 3 items (rough)")).toBeTruthy();
    expect(input("Max cost (USD)").value).toBe("0.18");
    fireEvent.change(input("Max cost (USD)"), { target: { value: "" } }); fireEvent.click(run());
    expect(onRun).toHaveBeenCalledWith({ dataset: "fictional-alpha", split: "validation" });
  });
  it.each(["0", "-1", "1.5", "abc"])("rejects N=%s", async n => {
    const { requests } = setup(); await tick(0); fireEvent.change(input("N"), { target: { value: n } }); await tick();
    expect(run().disabled).toBe(true); expect(screen.getByText("N must be an integer of at least 1.")).toBeTruthy(); expect(requests).toEqual([]);
  });
  it.each(["0", "-1", "abc"])("rejects cap=%s", async cap => {
    setup(); await tick(0); fireEvent.change(input("Max cost (USD)"), { target: { value: cap } }); expect(run().disabled).toBe(true);
    expect(screen.getByText("Max cost must be greater than 0, or blank for no cap.")).toBeTruthy();
  });
  it("clamps split and all-split sizes on blur", async () => {
    const { onRun } = setup(); await tick(0);
    fireEvent.change(input("N"), { target: { value: "8" } }); fireEvent.blur(input("N"));
    expect(input("N").value).toBe("3"); expect(screen.getByText("N clamped to 3")).toBeTruthy();
    fireEvent.change(screen.getByLabelText("Split"), { target: { value: "all" } });
    fireEvent.change(input("N"), { target: { value: "8" } }); fireEvent.blur(input("N")); expect(input("N").value).toBe("5"); await tick();
    fireEvent.click(run()); expect(onRun).toHaveBeenCalledWith({ dataset: "fictional-alpha", split: "all", n: 5, max_cost_usd: 0.18 });
  });
  it("shows held-out guidance without blocking", async () => {
    setup(); await tick(0); await tick(); fireEvent.change(screen.getByLabelText("Split"), { target: { value: "test" } }); await tick();
    expect(screen.getByText(metadata.test_split_note)).toBeTruthy(); expect(run().disabled).toBe(false);
  });
  it.each([unknown.note, ""])("shows unknown cost note or pilot fallback", async note => {
    setup(false, { ...unknown, note } as Estimate); await tick(0); await tick();
    expect(screen.getByText(note || unknown.note)).toBeTruthy(); expect(input("Max cost (USD)").value).toBe(""); expect(run().disabled).toBe(false);
  });
  it("preserves explicit cap and blank edits across estimates", async () => {
    const { setEstimate } = setup(); await tick(0); await tick();
    fireEvent.change(input("Max cost (USD)"), { target: { value: "2.50" } }); fireEvent.change(input("N"), { target: { value: "1" } }); await tick();
    expect(input("Max cost (USD)").value).toBe("2.50");
    fireEvent.change(input("Max cost (USD)"), { target: { value: "" } }); setEstimate({ ...known, est_cost_usd: 1 } as Estimate);
    fireEvent.change(input("N"), { target: { value: "2" } }); await tick(); expect(input("Max cost (USD)").value).toBe("");
  });
  it("clears an untouched cap for unknown estimates", async () => {
    const { setEstimate } = setup(); await tick(0); await tick(); setEstimate(unknown as Estimate);
    fireEvent.change(input("N"), { target: { value: "1" } }); await tick(); expect(input("Max cost (USD)").value).toBe("");
  });
  it("persists dataset and resets split", async () => {
    const first = setup(); await tick(0); fireEvent.change(screen.getByLabelText("Split"), { target: { value: "all" } });
    fireEvent.change(screen.getByLabelText("Dataset"), { target: { value: "fictional-beta" } }); await tick(0);
    expect((screen.getByLabelText("Split") as HTMLSelectElement).value).toBe("validation"); first.unmount(); setup(); await tick(0);
    expect((screen.getByLabelText("Dataset") as HTMLSelectElement).value).toBe("fictional-beta");
  });
  it("works with unavailable storage", async () => {
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => { throw Error("denied"); });
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => { throw Error("denied"); });
    setup(); await tick(0); await tick(); expect(run().disabled).toBe(false);
  });
  it("explains no datasets", async () => {
    setup(true); await tick(0); expect(screen.getByText("No datasets in eval/datasets/")).toBeTruthy(); expect(screen.queryByRole("button", { name: "Run" })).toBeNull();
  });
});

describe("RunPanel request lifetime", () => {
  it("aborts old metadata on selection and does not apply its late splits", async () => {
    let resolve!: (response: Response) => void;
    let oldSignal: AbortSignal | null | undefined;
    const api = createEvalApi({ fetch: (async (url, opts) => {
      if (url === "/eval-api/datasets") return Response.json(datasets);
      if (url === "/eval-api/datasets/fictional-alpha") { oldSignal = opts?.signal; return new Promise<Response>(done => { resolve = done; }); }
      if (url === "/eval-api/datasets/fictional-beta") return Response.json({ ...metadata, name: "fictional-beta", default_split: "test" });
      if (url === "/eval-api/runs/estimate") return Response.json(unknown);
      throw Error(`Unexpected offline request ${url}`);
    }) as typeof fetch });
    render(<RunPanel api={api} />); await tick(0);
    fireEvent.change(screen.getByLabelText("Dataset"), { target: { value: "fictional-beta" } }); await tick(0);
    expect(oldSignal?.aborted).toBe(true);
    await act(async () => resolve(Response.json(metadata)));
    expect((screen.getByLabelText("Split") as HTMLSelectElement).value).toBe("test");
  });
  it("aborts stale estimates on selection and on unmount", async () => {
    const pending: { signal: AbortSignal | null | undefined; resolve: (response: Response) => void }[] = [];
    const api = createEvalApi({ fetch: (async (url, opts) => {
      if (url === "/eval-api/datasets") return Response.json(datasets);
      if (String(url).startsWith("/eval-api/datasets/")) return Response.json({ ...metadata, name: String(url).split("/").at(-1) });
      if (url === "/eval-api/runs/estimate") return new Promise<Response>(resolve => pending.push({ signal: opts?.signal, resolve }));
      throw Error(`Unexpected offline request ${url}`);
    }) as typeof fetch });
    const { unmount } = render(<RunPanel api={api} />); await tick(0); await tick();
    fireEvent.change(screen.getByLabelText("Dataset"), { target: { value: "fictional-beta" } }); await tick(0);
    expect(pending[0].signal?.aborted).toBe(true);
    await act(async () => pending[0].resolve(Response.json(known)));
    expect(screen.queryByText("~$0.12 for 3 items (rough)")).toBeNull();
    expect(input("Max cost (USD)").value).toBe(""); await tick();
    unmount(); expect(pending[1].signal?.aborted).toBe(true);
    await tick(1000); expect(pending).toHaveLength(2);
  });
  it("does not clamp when a split size is unknown", async () => {
    const api = createEvalApi({ fetch: (async url => {
      if (url === "/eval-api/datasets") return Response.json(datasets);
      return Response.json({ ...metadata, splits: [{ name: "test", size: null }], default_split: "test" });
    }) as typeof fetch });
    render(<RunPanel api={api} />); await tick(0);
    fireEvent.change(input("N"), { target: { value: "100" } }); fireEvent.blur(input("N")); await tick();
    expect(input("N").value).toBe("100"); expect(run().disabled).toBe(false);
  });
  it("keeps Run disabled while a cap-prefilling estimate is pending (fail closed)", async () => {
    const { onRun } = setup(); await tick(0); await tick();
    expect(input("Max cost (USD)").value).toBe("0.18");
    fireEvent.change(input("N"), { target: { value: "2" } });
    expect(run().disabled).toBe(true);
    fireEvent.submit(run().closest("form")!); expect(onRun).not.toHaveBeenCalled();
    await tick(); expect(run().disabled).toBe(false); fireEvent.click(run());
    expect(onRun).toHaveBeenCalledWith(expect.objectContaining({ n: 2, max_cost_usd: 0.18 }));
  });
  it("lets an explicit blank cap run without waiting for an estimate", async () => {
    const { onRun } = setup(); await tick(0); await tick();
    fireEvent.change(input("Max cost (USD)"), { target: { value: "" } });
    fireEvent.change(input("N"), { target: { value: "2" } }); expect(run().disabled).toBe(false);
    fireEvent.click(run()); expect(onRun).toHaveBeenCalledWith({ dataset: "fictional-alpha", split: "validation", n: 2 });
  });
});
