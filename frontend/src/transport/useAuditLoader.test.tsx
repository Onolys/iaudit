// @vitest-environment jsdom
import { act, cleanup, renderHook, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { AuditDeps } from "./runAudit";
import { useAuditLoader } from "./useAuditLoader";

import requestA from "@contracts/examples/request.json?raw";
import responseA from "@contracts/examples/response.json?raw";
const requestB = JSON.stringify({ ...JSON.parse(requestA), request_id: "req-b" });
const responseB = JSON.stringify({ ...JSON.parse(responseA), request_id: "req-b" });
const file = (text: string, name = "r.json") => new File([text], name);

afterEach(cleanup);

interface Pending {
  body: string;
  resolve: (r: Response) => void;
  signal: AbortSignal;
}

/** fetch whose responses are released manually. */
function manualFetch() {
  const calls: Pending[] = [];
  const fn = vi.fn((_u: unknown, init?: RequestInit) =>
    new Promise<Response>((resolve, reject) => {
      const signal = init!.signal as AbortSignal;
      signal.addEventListener("abort", () => reject(new DOMException("a", "AbortError")));
      calls.push({ body: init!.body as string, resolve, signal });
    }),
  );
  return { fn, calls };
}

const deps = (f: typeof fetch): AuditDeps => ({
  fetch: f,
  config: { mock: false, auditUrl: "https://audit.example/api" },
  registry: [],
});

function setup() {
  const m = manualFetch();
  const hook = renderHook(() => useAuditLoader(deps(m.fn as unknown as typeof fetch)));
  return { m, ...hook };
}

describe("useAuditLoader", () => {
  it("starts idle, shows loading immediately, then ok", async () => {
    const { m, result } = setup();
    expect(result.current.state).toEqual({ status: "idle" });
    act(() => void result.current.loadFile(file(requestA, "a.json")));
    expect(result.current.state).toMatchObject({ status: "loading", fileName: "a.json" });
    await waitFor(() => expect(m.calls).toHaveLength(1));
    expect(result.current.state).toMatchObject({ status: "loading", requestId: "example-001" });
    expect(JSON.parse(m.calls[0].body)).toEqual(JSON.parse(requestA));
    await act(async () => m.calls[0].resolve(new Response(responseA)));
    expect(result.current.state).toMatchObject({ status: "ok", fileName: "a.json", result: { source: "service" } });
  });

  it("invalid file -> error, fetch never called", async () => {
    const { m, result } = setup();
    await act(async () => void (await result.current.loadFile(file("{nope"))));
    expect(result.current.state).toMatchObject({ status: "error", error: { kind: "invalid_request_file" } });
    expect(m.fn).not.toHaveBeenCalled();
  });

  it("uploading B while A is in flight leaves only B's result", async () => {
    const { m, result } = setup();
    act(() => void result.current.loadFile(file(requestA, "a.json")));
    await waitFor(() => expect(m.calls).toHaveLength(1));
    act(() => void result.current.loadFile(file(requestB, "b.json")));
    await waitFor(() => expect(m.calls).toHaveLength(2));
    expect(m.calls[0].signal.aborted).toBe(true);
    await act(async () => m.calls[1].resolve(new Response(responseB)));
    // A's late reply is ignored
    await act(async () => m.calls[0].resolve(new Response(responseA)));
    expect(result.current.state).toMatchObject({ status: "ok", fileName: "b.json" });
    expect((result.current.state as { result: { response: { request_id: string } } }).result.response.request_id).toBe("req-b");
  });

  it("retry resends the identical body after a retryable error", async () => {
    const { m, result } = setup();
    act(() => void result.current.loadFile(file(requestA)));
    await waitFor(() => expect(m.calls).toHaveLength(1));
    await act(async () => m.calls[0].resolve(new Response("oops", { status: 503 })));
    expect(result.current.state).toMatchObject({ status: "error", error: { kind: "http_5xx", status: 503 } });
    act(() => result.current.retry());
    expect(result.current.state).toMatchObject({ status: "loading", fileName: "r.json" });
    await waitFor(() => expect(m.calls).toHaveLength(2));
    expect(m.calls[1].body).toBe(m.calls[0].body);
    await act(async () => m.calls[1].resolve(new Response(responseA)));
    expect(result.current.state.status).toBe("ok");
  });

  it("retry is a no-op after a non-retryable error", async () => {
    const { m, result } = setup();
    act(() => void result.current.loadFile(file(requestA)));
    await waitFor(() => expect(m.calls).toHaveLength(1));
    await act(async () => m.calls[0].resolve(new Response("bad", { status: 400 })));
    const before = result.current.state;
    act(() => result.current.retry());
    expect(result.current.state).toBe(before);
    expect(m.calls).toHaveLength(1);
  });

  it("retry is a no-op when idle", () => {
    const { m, result } = setup();
    act(() => result.current.retry());
    expect(result.current.state).toEqual({ status: "idle" });
    expect(m.fn).not.toHaveBeenCalled();
  });

  it("cancel aborts the request and shows cancelled; retry then works", async () => {
    const { m, result } = setup();
    act(() => void result.current.loadFile(file(requestA)));
    await waitFor(() => expect(m.calls).toHaveLength(1));
    act(() => result.current.cancel());
    await waitFor(() => expect(result.current.state).toMatchObject({ status: "error", error: { kind: "cancelled" } }));
    expect(m.calls[0].signal.aborted).toBe(true);
    act(() => result.current.retry());
    await waitFor(() => expect(m.calls).toHaveLength(2));
  });

  it("unmount aborts the in-flight request", async () => {
    const { m, result, unmount } = setup();
    act(() => void result.current.loadFile(file(requestA)));
    await waitFor(() => expect(m.calls).toHaveLength(1));
    unmount();
    expect(m.calls[0].signal.aborted).toBe(true);
  });

  it("reset returns to idle and drops the in-flight result", async () => {
    const { m, result } = setup();
    act(() => void result.current.loadFile(file(requestA)));
    await waitFor(() => expect(m.calls).toHaveLength(1));
    act(() => result.current.reset());
    expect(result.current.state).toEqual({ status: "idle" });
    await act(async () => m.calls[0].resolve(new Response(responseA)));
    expect(result.current.state).toEqual({ status: "idle" });
  });

  it("cancel while mock fixtures are still loading shows cancelled, not the audit", async () => {
    let release!: (t: string) => void;
    const slow = new Promise<string>((r) => (release = r));
    const registry = [{ name: "default", loadRequest: () => Promise.resolve(requestA), loadResponse: () => slow }];
    const { result } = renderHook(() =>
      useAuditLoader({ fetch: vi.fn() as never, config: { mock: true, auditUrl: null }, registry, mockDelayMs: 0 }),
    );
    act(() => void result.current.loadFile(file(requestA)));
    await waitFor(() => expect(result.current.state).toMatchObject({ status: "loading", requestId: "example-001" }));
    await act(async () => await new Promise((r) => setTimeout(r, 10)));
    act(() => result.current.cancel());
    await act(async () => release(responseA));
    expect(result.current.state).toMatchObject({ status: "error", error: { kind: "cancelled" } });
  });

  it("a rejecting file read ends in an error, not endless loading", async () => {
    const { result } = setup();
    const bad = { name: "x.json", text: () => Promise.reject(new Error("NotReadable")) } as unknown as File;
    await act(async () => void (await result.current.loadFile(bad)));
    expect(result.current.state).toMatchObject({ status: "error", error: { kind: "invalid_request_file" } });
  });

  it("a failing mock fixture load ends in an error", async () => {
    const registry = [{ name: "default", loadRequest: () => Promise.reject(new Error("chunk")), loadResponse: async () => "" }];
    const { result } = renderHook(() =>
      useAuditLoader({ fetch: vi.fn() as never, config: { mock: true, auditUrl: null }, registry, mockDelayMs: 0 }),
    );
    await act(async () => void (await result.current.loadFile(file(requestA))));
    expect(result.current.state).toMatchObject({ status: "error", error: { kind: "network" } });
  });
});
