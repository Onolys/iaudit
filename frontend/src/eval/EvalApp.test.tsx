// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import EvalApp, { type EvalView } from "./EvalApp";
import { ServerBanner, EvalErrorMessage } from "./ServerBanner";
import { createEvalApi } from "./evalApi";
import type { EvalError, Health } from "./evalTypes";
import type { Result } from "../contract";
import finished from "./fixtures/run-finished.json";
import metrics from "./fixtures/metrics.json";
import items from "./fixtures/items.json";
import saved from "./fixtures/item-ok.json";
import comparison from "./fixtures/comparison.json";

const healthy = { eval_api_version: "1.0.0", backend: { url: "http://backend.invalid", reachable: true } };
const fakeApi = (fetcher: typeof fetch = async () => Response.json(healthy)) => createEvalApi({ fetch: async (url, opts) => (String(url).endsWith("/datasets") || String(url).endsWith("/runs")) ? Response.json([]) : fetcher(url, opts) });
const deferred = <T,>() => {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>(done => { resolve = done; });
  return { promise, resolve };
};
afterEach(() => { cleanup(); vi.unstubAllGlobals(); vi.unstubAllEnvs(); });

describe("EvalApp", () => {
  it("opens the Run and Runs sections after a healthy mount", async () => {
    render(<EvalApp api={fakeApi()} />);
    expect(screen.getByRole("region", { name: "Run" })).toBeTruthy();
    expect(screen.getByRole("region", { name: "Runs" })).toBeTruthy();
    await waitFor(() => expect(screen.queryByRole("status")).toBeNull());
    expect(screen.queryByRole("alert")).toBeNull();
  });
  it("uses the configured eval base for its default client's health request", async () => {
    vi.stubEnv("VITE_EVAL_API_BASE", "/custom-eval");
    vi.stubGlobal("fetch", (async (url: string | URL | Request) => {
      if (url === "/custom-eval/datasets" || url === "/custom-eval/runs") return Response.json([]);
      if (url !== "/custom-eval/health") throw new Error("unexpected URL");
      return Response.json(healthy);
    }) as typeof fetch);
    render(<EvalApp />);
    expect(screen.getByRole("status").textContent).toContain("Checking eval server");
    await waitFor(() => expect(screen.queryByRole("status")).toBeNull());
    expect(screen.queryByRole("alert")).toBeNull();
  });
  it("shows a server banner on failure and Retry clears it on recovery", async () => {
    let reachable = false;
    render(<EvalApp api={fakeApi(async () => {
      if (!reachable) throw new Error("offline");
      return Response.json(healthy);
    })} />);
    await screen.findByRole("alert");
    expect(screen.getByText("Eval server not reachable")).toBeTruthy();
    reachable = true;
    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    await waitFor(() => expect(screen.queryByRole("alert")).toBeNull());
  });
  it.each<{ view: EvalView; back: string; context: string[] }>([
    { view: { view: "run", runId: finished.run_id }, back: "Back to runs", context: ["fixture-created"] },
    { view: { view: "item", runId: finished.run_id, itemId: saved.item_id, from: "run" }, back: "Back to run", context: [`${finished.run_id} - ${saved.item_id}`] },
    { view: { view: "compare", a: comparison.run_a, b: comparison.run_b }, back: "Back", context: [`A: ${comparison.run_a}`, `B: ${comparison.run_b}`] },
  ])("renders the real $view.view view with its selected identifiers", async ({ view, back, context }) => {
    const api = createEvalApi({ fetch: async url => {
      const path = String(url);
      if (path.endsWith("/health")) return Response.json(healthy);
      if (path.includes("/compare?")) return Response.json(comparison);
      if (path.endsWith("/metrics")) return Response.json(metrics);
      if (path.includes("/items?")) return Response.json(items);
      if (path.includes("/items/")) return Response.json(saved);
      return Response.json(finished);
    } });
    render(<EvalApp api={api} initialView={view} />);
    for (const text of context) expect(await screen.findByText(text)).toBeTruthy();
    expect(screen.getByRole("button", { name: back })).toBeTruthy();
    expect(screen.queryByRole("region", { name: "Run" })).toBeNull();
    await waitFor(() => expect(screen.queryByText("Checking eval server…")).toBeNull());
  });
  it("aborts the health request on unmount", () => {
    let signal: AbortSignal | null | undefined;
    const { unmount } = render(<EvalApp api={fakeApi(async (_url, opts) => {
      signal = opts?.signal;
      return new Promise<Response>(() => {});
    })} />);
    expect(signal?.aborted).toBe(false);
    unmount();
    expect(signal?.aborted).toBe(true);
  });
  it("ignores a late retry failure after a newer retry succeeds", async () => {
    const pending = deferred<Result<Health, EvalError>>();
    let attempt = 0;
    let previousSignal: AbortSignal | undefined;
    const api = { ...fakeApi(), health: ({ signal }: { signal?: AbortSignal } = {}) => {
      attempt++;
      if (attempt === 1) return Promise.resolve({ ok: false as const, error: { kind: "unreachable" as const } });
      if (attempt === 2) { previousSignal = signal; return pending.promise; }
      return Promise.resolve({ ok: true as const, value: healthy });
    } };
    render(<EvalApp api={api} />);
    await screen.findByRole("alert");
    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    expect(previousSignal?.aborted).toBe(true);
    await waitFor(() => expect(screen.queryByRole("alert")).toBeNull());
    await act(async () => pending.resolve({ ok: false, error: { kind: "unreachable" } }));
    expect(screen.queryByRole("alert")).toBeNull();
  });
});

describe("shared eval error presentation", () => {
  it.each<{ error: EvalError; text: string }>([
    { error: { kind: "unreachable" }, text: "Eval server not reachable" },
    { error: { kind: "timeout", seconds: 10 }, text: "Eval request timed out after 10 seconds" },
    { error: { kind: "cancelled" }, text: "Eval request cancelled" },
    { error: { kind: "bad_body", message: "Malformed response" }, text: "Malformed response" },
  ])("explains $error.kind errors", ({ error, text }) => {
    render(<EvalErrorMessage error={error} />);
    expect(screen.getByText(text)).toBeTruthy();
  });
  it("shows lost contact while preserving the caller's content", () => {
    render(<><ServerBanner lostContact /><p>Progress: 2 of 5</p></>);
    expect(screen.getByRole("alert").textContent).toContain("Lost contact with eval server — retrying");
    expect(screen.getByText("Progress: 2 of 5")).toBeTruthy();
  });
  it("renders API message and structured detail as plain text", () => {
    const message = '<img src=x onerror="alert(1)">';
    const { container } = render(<EvalErrorMessage error={{ kind: "api", status: 409, code: "schema_mismatch", message, detail: { expected: "0.0.1", actual: "1.0.0", note: "<script>oops</script>" } }} />);
    expect(screen.getByText(message)).toBeTruthy();
    expect(container.textContent).toContain('"expected": "0.0.1"');
    expect(container.querySelector("img, script")).toBeNull();
  });
});
