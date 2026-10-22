// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { RunPanel } from "./RunPanel";
import { createEvalApi } from "./evalApi";
import datasets from "./fixtures/datasets.json";
import metadata from "./fixtures/dataset-detail.json";
import estimate from "./fixtures/estimate-unknown.json";
import running from "./fixtures/run-running.json";
import type { RunDetail } from "./evalTypes";
const tick = async (ms = 0) => { await act(async () => { await vi.advanceTimersByTimeAsync(ms); }); };
function setup({ missing = false, reload = false } = {}) {
  let detail = structuredClone(running) as RunDetail;
  let startError: {code: string; message: string; detail?: unknown} | null = null;
  let download = { status: "downloading", error: null as string | null };
  let misses = false;
  let abortResolve: ((r: Response) => void) | undefined;
  const changed = vi.fn();
  const fetch = vi.fn(async (url: RequestInfo | URL, init?: RequestInit): Promise<Response> => {
    const path = String(url); const post = init?.method === "POST";
    if (path.endsWith("/datasets")) return Response.json(datasets.map(d => ({...d, data_present: !missing})));
    if (path.endsWith("/download")) return Response.json(download);
    if (path.includes("/datasets/")) return Response.json(metadata);
    if (path.endsWith("/estimate")) return Response.json(estimate);
    if (path.endsWith("/abort")) return new Promise(resolve => { abortResolve = resolve; });
    if (path.endsWith("/runs") && !post) return Response.json(reload ? [{...running, progress: undefined, run_info: undefined}] : []);
    if (path.endsWith("/runs")) return startError ? Response.json({error: startError}, {status:409}) : Response.json({run_id: running.run_id}, {status:202});
    if (path.endsWith(`/runs/${running.run_id}`)) { if (misses) throw Error("offline"); return Response.json(detail); }
    throw Error(`Unexpected offline request ${path}`);
  });
  const rendered = render(<RunPanel api={createEvalApi({fetch: fetch as typeof globalThis.fetch})} onRunsChanged={changed} />);
  return { ...rendered, fetch, changed, failPolls: (v: boolean) => {misses=v;}, setDetail: (v: RunDetail) => {detail=v;}, setStartError: (v: typeof startError) => {startError=v;}, setDownload: (status: string, error: string | null = null) => {download={status,error}; if(status === "ready") missing=false;}, finishAbort: () => abortResolve!(Response.json({...running, progress: undefined, run_info: undefined})) };
}
beforeEach(() => {localStorage.clear(); vi.useFakeTimers();});
afterEach(() => {cleanup(); vi.useRealTimers();});
const start = () => fireEvent.click(screen.getByRole("button", {name:"Run"}));
it("starts, updates progress and optional cost, aborts once and signals list refresh", async () => {
  const s=setup(); await tick(); await tick(400); start(); await tick();
  expect(screen.getByRole("progressbar").getAttribute("value")).toBe("1");
  expect(screen.queryByText(/Cost:/)).toBeNull(); expect(s.changed).toHaveBeenCalledTimes(1);
  s.setDetail({...running, progress:{done:2,total:3,failures:1,cost_usd:0.12}} as RunDetail); await tick(1000);
  expect(screen.getByText("Failures: 1")).toBeTruthy(); expect(screen.getByText("Cost: $0.12")).toBeTruthy();
  fireEvent.click(screen.getByRole("button", {name:"Abort"}));
  expect((screen.getByRole("button", {name:"Aborting…"}) as HTMLButtonElement).disabled).toBe(true);
  await act(async () => s.finishAbort()); expect(s.changed).toHaveBeenCalledTimes(2);
  s.setDetail({...running,state:"aborted"} as RunDetail); await tick(1000);
  expect(screen.getByText("aborted")).toBeTruthy(); expect(screen.queryByRole("button", {name:"Abort"})).toBeNull();
  expect(s.changed).toHaveBeenCalledTimes(3);
});
it("offers missing data download, failure retry, then refreshes datasets and restores Run", async () => {
  const s=setup({missing:true}); await tick(); fireEvent.click(screen.getByRole("button",{name:"Download data"})); await tick();
  expect(screen.getByText("downloading…")).toBeTruthy(); s.setDownload("failed","Fictional download failure"); await tick(1000);
  expect(screen.getByText("Fictional download failure")).toBeTruthy();
  s.setDownload("downloading"); fireEvent.click(screen.getByRole("button",{name:"Retry download"})); await tick();
  s.setDownload("ready"); await tick(1000); expect(screen.getByRole("button",{name:"Run"})).toBeTruthy();
  expect(s.fetch.mock.calls.filter(([url]) => String(url).endsWith("/datasets"))).toHaveLength(2);
});
it("handles data_missing 409 even when dataset was present", async () => {
  const s=setup(); await tick(); await tick(400); s.setStartError({code:"data_missing",message:"Download first"}); start(); await tick();
  expect(screen.getByRole("button",{name:"Download data"})).toBeTruthy();
});
it("attaches to run_active 409", async () => {
  const s=setup(); await tick(); await tick(400); s.setStartError({code:"run_active",message:"busy",detail:{run_id:running.run_id}}); start(); await tick();
  expect(screen.getByText(`Run ${running.run_id} is already active`)).toBeTruthy(); fireEvent.click(screen.getByRole("button",{name:"Attach to active run"})); await tick();
  expect(screen.getByRole("progressbar")).toBeTruthy();
});
it("reattaches on reload, shows lost contact after three misses, then recovers", async () => {
  const s=setup({reload:true}); await tick(); expect(screen.getByRole("progressbar")).toBeTruthy();
  s.failPolls(true); await tick(3000); expect(screen.getByText("Lost contact with eval server — retrying")).toBeTruthy();
  s.failPolls(false); await tick(1000); expect(screen.queryByText("Lost contact with eval server — retrying")).toBeNull();
  s.unmount(); const count=s.fetch.mock.calls.length; await tick(10000); expect(s.fetch).toHaveBeenCalledTimes(count);
});
it("shows failed state and the server's actual cost error", async () => {
  const s=setup({reload:true}); s.setDetail({...running,state:"failed",error:{kind:"cost_missing",message:"No cost was returned",extra:"preserved"}} as RunDetail); await tick();
  expect(screen.getByText("failed")).toBeTruthy(); expect(screen.getByText("No cost was returned")).toBeTruthy();
});
it.each(["schema_mismatch","backend_unreachable"])("preserves %s message and detail", async code => {
  const s=setup(); await tick(); await tick(400); s.setStartError({code,message:"Exact server message",detail:{expected:"1.2.0",actual:"0.0.0"}}); start(); await tick();
  expect(screen.getByText("Exact server message")).toBeTruthy(); expect(screen.getByText(/"actual": "0.0.0"/)).toBeTruthy();
});
it("retry after a failed download shows downloading, not the old failure", async () => {
  const s=setup({missing:true}); await tick(); fireEvent.click(screen.getByRole("button",{name:"Download data"})); await tick();
  s.setDownload("failed","Old failure"); await tick(1000); expect(screen.getByText("Old failure")).toBeTruthy();
  s.setDownload("downloading"); fireEvent.click(screen.getByRole("button",{name:"Retry download"})); await tick();
  expect(screen.queryByText("Old failure")).toBeNull(); expect(screen.getByText("downloading…")).toBeTruthy();
});
it("a retry does not take a previous attempt's ready as its own", async () => {
  const s=setup({missing:true}); await tick(); fireEvent.click(screen.getByRole("button",{name:"Download data"})); await tick();
  s.setDownload("failed","Old failure"); await tick(1000);
  s.setDownload("downloading"); fireEvent.click(screen.getByRole("button",{name:"Retry download"})); await tick();
  expect(screen.getByText("downloading…")).toBeTruthy(); expect(screen.queryByRole("button",{name:"Run"})).toBeNull();
});
it("a second dataset does not inherit the first one's download failure", async () => {
  const s=setup({missing:true}); await tick(); fireEvent.click(screen.getByRole("button",{name:"Download data"})); await tick();
  s.setDownload("failed","Alpha failure"); await tick(1000); expect(screen.getByText("Alpha failure")).toBeTruthy();
  fireEvent.change(screen.getByLabelText("Dataset"),{target:{value:"fictional-beta"}}); await tick();
  expect(screen.queryByText("Alpha failure")).toBeNull(); expect(screen.getByRole("button",{name:"Download data"})).toBeTruthy();
});
it("ignores an abort timeout once the poll shows the run is no longer running", async () => {
  const s=setup(); await tick(); await tick(400); start(); await tick();
  fireEvent.click(screen.getByRole("button",{name:"Abort"}));
  s.setDetail({...running,state:"aborted"} as RunDetail); await tick(1000);
  await tick(120_000);
  expect(screen.queryByText(/timed out|timeout/i)).toBeNull(); expect(screen.getByText("aborted")).toBeTruthy();
});
it("gives abort a 120 s POST timeout", async () => {
  setup(); await tick(); await tick(400); start(); await tick();
  fireEvent.click(screen.getByRole("button",{name:"Abort"}));
  await tick(60_000); expect(screen.queryByText(/timed out|timeout/i)).toBeNull();
  expect((screen.getByRole("button",{name:"Aborting…"}) as HTMLButtonElement).disabled).toBe(true);
});
