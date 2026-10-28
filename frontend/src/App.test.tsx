// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import evalDatasets from "./eval/fixtures/datasets.json";
import evalMetadata from "./eval/fixtures/dataset-detail.json";
import evalEstimate from "./eval/fixtures/estimate-unknown.json";
import evalRunning from "./eval/fixtures/run-running.json";
import App from "./App";
import type { AuditDeps } from "./transport/runAudit";
import { createEvalApi } from "./eval/evalApi";

import requestRaw from "@contracts/examples/request.json?raw";
import responseRaw from "@contracts/examples/response.json?raw";

afterEach(cleanup);

const okDeps = (response = responseRaw, mock = false): AuditDeps => ({
  fetch: (async () => new Response(response, { status: 200 })) as typeof fetch,
  config: { mock, auditUrl: "https://audit.example/api" },
  registry: [],
});

const healthyEval = { eval_api_version: "1.0.0", backend: { url: "http://backend.invalid", reachable: true } };
const evalApi = (healthFetch?: typeof fetch) => createEvalApi({ fetch: async (url, options) => {
  if (String(url).endsWith("/health")) return healthFetch ? healthFetch(url, options) : Response.json(healthyEval);
  if (String(url).endsWith("/datasets") || String(url).endsWith("/runs")) return Response.json([]);
  throw new Error(`Unexpected eval URL: ${String(url)}`);
} });

describe("eaudit and Eval switch", () => {
  it("starts in eaudit and exposes the selected mode through pressed buttons", async () => {
    render(<App deps={okDeps()} evalApi={evalApi()} />);
    expect(screen.getByRole("button", { name: "eaudit", pressed: true })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Eval", pressed: false })).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Eval" }));
    expect(screen.getByRole("button", { name: "Eval", pressed: true })).toBeTruthy();
    expect(screen.getByRole("button", { name: "eaudit", pressed: false })).toBeTruthy();
    expect(screen.getByRole("region", { name: "Run" })).toBeTruthy();
    expect(screen.getByRole("region", { name: "Runs" })).toBeTruthy();
    expect(screen.queryByText("Upload a request JSON file to begin.")).toBeNull();
    await waitFor(() => expect(screen.queryByText("Checking eval server…")).toBeNull());
  });

  it("discards the loaded audit and review selection when returning from Eval", async () => {
    const { container } = render(<App deps={okDeps()} evalApi={evalApi()} />);
    await upload(container);
    await screen.findByText("example-001");
    fireEvent.click(screen.getByRole("button", { name: /Contradicted/ }));
    fireEvent.click(screen.getByRole("button", { name: "Eval" }));
    fireEvent.click(screen.getByRole("button", { name: "eaudit" }));
    expect(screen.getByText("Upload a request JSON file to begin.")).toBeTruthy();
    expect(screen.getByText("No request ID")).toBeTruthy();
    expect(screen.queryByText("req.json")).toBeNull();
    expect(screen.queryByText("example-001")).toBeNull();
    await upload(container);
    await screen.findByText("example-001");
    expect(container.querySelector('.verdict-count[aria-pressed="true"]')).toBeNull();
  });

  it("aborts an in-flight audit on switching away and ignores its late result", async () => {
    let signal: AbortSignal | null | undefined;
    let finish!: (response: Response) => void;
    const deps = { ...okDeps(), fetch: (async (_url, options) => {
      signal = options?.signal;
      return new Promise<Response>(resolve => { finish = resolve; });
    }) as typeof fetch };
    const { container } = render(<App deps={deps} evalApi={evalApi()} />);
    await upload(container);
    await waitFor(() => expect(signal?.aborted).toBe(false));
    fireEvent.click(screen.getByRole("button", { name: "Eval" }));
    expect(signal?.aborted).toBe(true);
    fireEvent.click(screen.getByRole("button", { name: "eaudit" }));
    await act(async () => finish(new Response(responseRaw, { status: 200 })));
    expect(screen.getByText("Upload a request JSON file to begin.")).toBeTruthy();
    expect(screen.queryByText("example-001")).toBeNull();
  });

  it("aborts Eval health on switching to eaudit and checks health afresh on return", async () => {
    let signal: AbortSignal | null | undefined;
    let finish!: (response: Response) => void;
    let calls = 0;
    const api = evalApi(async (_url, options) => {
      calls++;
      if (calls > 1) return Response.json(healthyEval);
      signal = options?.signal;
      return new Promise<Response>(resolve => { finish = resolve; });
    });
    render(<App deps={okDeps()} evalApi={api} />);
    fireEvent.click(screen.getByRole("button", { name: "Eval" }));
    expect(signal?.aborted).toBe(false);
    fireEvent.click(screen.getByRole("button", { name: "eaudit" }));
    expect(signal?.aborted).toBe(true);
    fireEvent.click(screen.getByRole("button", { name: "Eval" }));
    await waitFor(() => expect(screen.queryByText("Checking eval server…")).toBeNull());
    expect(calls).toBe(2);
    await act(async () => finish(new Response("offline", { status: 502 })));
    expect(screen.queryByRole("alert")).toBeNull();
    expect(screen.getByRole("region", { name: "Run" })).toBeTruthy();
  });

  it("stops every Eval fetch when toggled to eaudit mid-run, including an in-flight poll", async () => {
    vi.useFakeTimers();
    try {
      let pollSignal: AbortSignal | null | undefined;
      let polls = 0;
      const fetch = vi.fn(async (url: RequestInfo | URL, options?: RequestInit): Promise<Response> => {
        const path = String(url);
        if (path.endsWith("/health")) return Response.json(healthyEval);
        if (path.endsWith("/datasets")) return Response.json(evalDatasets);
        if (path.includes("/datasets/")) return Response.json(evalMetadata);
        if (path.endsWith("/estimate")) return Response.json(evalEstimate);
        if (path.endsWith("/runs")) return options?.method === "POST"
          ? Response.json({ run_id: evalRunning.run_id }, {status: 202}) : Response.json([]);
        if (path.endsWith(`/runs/${evalRunning.run_id}`)) {
          polls++;
          if (polls === 1) return Response.json(evalRunning);
          pollSignal = options?.signal;
          return new Promise<Response>(() => {});
        }
        throw Error(`Unexpected offline request ${path}`);
      });
      render(<App deps={okDeps()} evalApi={createEvalApi({ fetch: fetch as typeof globalThis.fetch })} />);
      fireEvent.click(screen.getByRole("button", {name: "Eval"}));
      await act(async () => { await vi.advanceTimersByTimeAsync(0); });
      await act(async () => { await vi.advanceTimersByTimeAsync(400); });
      fireEvent.click(screen.getByRole("button", {name: "Run"}));
      await act(async () => { await vi.advanceTimersByTimeAsync(0); });
      expect(screen.getByRole("progressbar")).toBeTruthy();
      await act(async () => { await vi.advanceTimersByTimeAsync(1000); });
      expect(pollSignal?.aborted).toBe(false);
      fireEvent.click(screen.getByRole("button", {name: "eaudit"}));
      expect(pollSignal?.aborted).toBe(true);
      const before = fetch.mock.calls.length;
      await act(async () => { await vi.advanceTimersByTimeAsync(60000); });
      expect(fetch).toHaveBeenCalledTimes(before);
      expect(screen.getByText("Upload a request JSON file to begin.")).toBeTruthy();
    } finally { cleanup(); vi.useRealTimers(); }
  });

  it("keeps eaudit usable when the Eval server is unreachable", async () => {
    const { container } = render(<App deps={okDeps()} evalApi={evalApi(async () => { throw new Error("offline"); })} />);
    fireEvent.click(screen.getByRole("button", { name: "Eval" }));
    await screen.findByText("Eval server not reachable");
    fireEvent.click(screen.getByRole("button", { name: "eaudit" }));
    expect(screen.queryByRole("alert")).toBeNull();
    await upload(container);
    await screen.findByText("example-001");
  });
});

const input = (c: HTMLElement) => c.querySelector('input[type="file"]') as HTMLInputElement;
const upload = async (c: HTMLElement, text = requestRaw, name = "req.json") => {
  await act(async () => {
    fireEvent.change(input(c), { target: { files: [new File([text], name)] } });
  });
};

describe("App screen", () => {
  it("shows the idle prompt and a hidden file input accepting JSON", () => {
    const { container } = render(<App deps={okDeps()} />);
    expect(screen.getByText("Upload a request JSON file to begin.")).toBeTruthy();
    expect(input(container).accept).toBe(".json,application/json");
    expect(input(container).hidden).toBe(true);
    expect(screen.getByText("No request ID")).toBeTruthy();
  });

  it("shows header file name, request_id and five counts after load", async () => {
    const { container } = render(<App deps={okDeps()} />);
    await upload(container);
    await waitFor(() => expect(screen.getByText("example-001")).toBeTruthy());
    expect(screen.getByText("req.json")).toBeTruthy();
    const counts = container.querySelectorAll("header .verdict-count");
    expect(counts).toHaveLength(5);
    for (const c of counts) expect(c.querySelector("strong")!.textContent).toBe("1");
    expect(screen.queryByText("Mock data")).toBeNull();
  });

  it("shows the Mock data chip for mock results", async () => {
    const mockDeps: AuditDeps = {
      ...okDeps(),
      config: { mock: true, auditUrl: null },
      registry: [{ name: "default", loadRequest: async () => requestRaw, loadResponse: async () => responseRaw }],
      mockDelayMs: 0,
    };
    const { container } = render(<App deps={mockDeps} />);
    await upload(container);
    await waitFor(() => expect(screen.getByText("Mock data")).toBeTruthy());
  });

  it("shows the error screen and no stale audit", async () => {
    const { container } = render(<App deps={okDeps()} />);
    await upload(container);
    await waitFor(() => screen.getByText("example-001"));
    await upload(container, "not json", "bad.json");
    await waitFor(() => expect(screen.getByRole("alert")).toBeTruthy());
    expect(container.querySelectorAll(".verdict-count")).toHaveLength(0);
    expect(screen.queryByText("example-001")).toBeNull();
  });

  it("resets the input value so the same file fires again, and resets the review", async () => {
    const { container } = render(<App deps={okDeps()} />);
    await upload(container);
    await waitFor(() => screen.getByText("example-001"));
    fireEvent.click(container.querySelector(".verdict-count")!);
    expect(container.querySelector('.verdict-count[aria-pressed="true"]')).toBeTruthy();
    await upload(container);
    await waitFor(() => expect(container.querySelector('.verdict-count[aria-pressed="true"]')).toBeNull());
    expect(input(container).value).toBe("");
  });

  it("clicking a header count marks it pressed", async () => {
    const { container } = render(<App deps={okDeps()} />);
    await upload(container);
    await waitFor(() => screen.getByText("example-001"));
    fireEvent.click(screen.getByRole("button", { name: /Contradicted/ }));
    expect(screen.getByRole("button", { name: /Contradicted/ }).getAttribute("aria-pressed")).toBe("true");
  });
});
