// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { RunDetail } from "./RunDetail";
import { createEvalApi } from "./evalApi";
import finished from "./fixtures/run-finished.json";
import metrics from "./fixtures/metrics.json";
import items from "./fixtures/items.json";
import type { MetricsReport, RunDetail as Detail } from "./evalTypes";
const tick=async(ms=0)=>{await act(async()=>{await vi.advanceTimersByTimeAsync(ms);});};
beforeEach(()=>vi.useFakeTimers());afterEach(()=>{cleanup();vi.useRealTimers();});
function setup(initial:Detail=finished as Detail, options: {holdMetrics?: boolean; report?: MetricsReport | null; holdPost?: boolean} = {}) {
  let run=structuredClone(initial);
  let report:MetricsReport|null=options.report === undefined ? structuredClone(metrics) as MetricsReport : options.report;
  let miss=false;
  let postError=false;
  let pendingPoll=false;
  let pendingMetrics=options.holdMetrics ?? false;
  const signals:AbortSignal[]=[];
  const pendingPolls: {resolve:(response:Response)=>void;signal:AbortSignal}[]=[];
  const pendingReports: {resolve:(response:Response)=>void;signal:AbortSignal}[]=[];
  const fetch=vi.fn(async(url:RequestInfo|URL,opts?:RequestInit):Promise<Response>=>{
    const path=String(url);
    if(opts?.signal)signals.push(opts.signal);
    if(path.endsWith("/rescore")) {
      if(options.holdPost)return new Promise<Response>(()=>{});
      if(postError)return Response.json({error:{code:"bad_state",message:"Scoring already active.",detail:{state:"running"}}},{status:409});
      run={...run,score_state:"running"};return Response.json({...run,progress:undefined,run_info:undefined,error:undefined},{status:202});
    }
    if(path.endsWith("/metrics")) {
      if(pendingMetrics)return new Promise(resolve=>pendingReports.push({resolve,signal:opts!.signal!}));
      return report ? Response.json(report) : Response.json({error:{code:"not_found",message:"Metrics not available"}},{status:404});
    }
    if(path.includes("/items?"))return Response.json(items);
    if(miss)throw Error("offline");
    if(pendingPoll)return new Promise(resolve=>pendingPolls.push({resolve,signal:opts!.signal!}));
    return Response.json(run);
  });
  const api=createEvalApi({fetch:fetch as typeof globalThis.fetch});
  const onBack=vi.fn(),onOpenItem=vi.fn();
  const props={api,runId:initial.run_id,onBack,onOpenItem};
  return {...render(<RunDetail {...props}/>),props,fetch,onBack,onOpenItem,signals,pendingPolls,pendingReports,
    setRun:(value:Detail)=>{run=value;},setMetrics:(value:MetricsReport|null)=>{report=value;},miss:(value:boolean)=>{miss=value;},postError:()=>{postError=true;},holdPoll:()=>{pendingPoll=true;},holdMetrics:()=>{pendingMetrics=true;},
    releasePoll:(response:Response)=>{pendingPoll=false;pendingPolls.shift()!.resolve(response);},releaseMetrics:(response:Response)=>{pendingMetrics=false;pendingReports.shift()!.resolve(response);}};
}
const rescore=()=>screen.getByRole("button",{name:"Re-score"}) as HTMLButtonElement;
it("composes metrics, items, provenance, state and navigation",async()=>{
  const s=setup();await tick();
  expect(screen.getByRole("heading",{name:/fictional-alpha.*validation.*N=3/})).toBeTruthy();
  expect(screen.getByText("fixture-created")).toBeTruthy();expect(screen.getByText("finished")).toBeTruthy();
  expect(screen.getByRole("region",{name:"Run information"})).toBeTruthy();expect(screen.getByRole("table",{name:"Run items"})).toBeTruthy();
  fireEvent.click(screen.getByRole("button",{name:"Back to runs"}));expect(s.onBack).toHaveBeenCalledTimes(1);
  fireEvent.click(screen.getByRole("button",{name:items.items[0].label!}));expect(s.onOpenItem).toHaveBeenCalledWith(items.items[0].item_id);
});
it("polls pending scoring to terminal, then reads fresh metrics",async()=>{
  const s=setup({...finished,score_state:"pending"} as Detail,{report:null});await tick();
  expect(screen.getByText("Scoring...")).toBeTruthy();expect(rescore().disabled).toBe(true);
  s.setRun({...finished,score_state:"running"} as Detail);await tick(1000);expect(screen.getByText("Scoring...")).toBeTruthy();
  s.setRun(finished as Detail);s.setMetrics(metrics as MetricsReport);await tick(1000);
  expect(screen.queryByText("Scoring...")).toBeNull();expect(screen.getByText(/Primary counts them wrong/)).toBeTruthy();
  expect(s.fetch.mock.calls.filter(([url])=>String(url).endsWith("/metrics"))).toHaveLength(2);
  const calls=s.fetch.mock.calls.length;await tick(5000);expect(s.fetch).toHaveBeenCalledTimes(calls);
});
it("rescores after initial terminal data without stopping on the old snapshot",async()=>{
  const s=setup();await tick();fireEvent.click(rescore());await tick();
  expect(rescore().disabled).toBe(true);expect(screen.getByText("Scoring...")).toBeTruthy();
  const reads=()=>s.fetch.mock.calls.filter(([url])=>String(url).endsWith(`/${finished.run_id}`)).length;
  expect(reads()).toBe(2);
  const fresh=structuredClone(metrics) as MetricsReport;
  fresh.entries.find(entry=>entry.policy === "primary")!.value=0.91;
  s.setMetrics(fresh);s.setRun(finished as Detail);await tick(1000);expect(reads()).toBe(3);expect(rescore().disabled).toBe(false);expect(screen.getByText("0.91")).toBeTruthy();
  expect(s.fetch.mock.calls.filter(([url])=>String(url).endsWith("/metrics"))).toHaveLength(2);
});
it("shows a 409 rescore error verbatim and keeps retry available",async()=>{
  const s=setup();await tick();s.postError();fireEvent.click(rescore());await tick();
  expect(screen.getByText("Scoring already active.")).toBeTruthy();expect(screen.getByText(/"state": "running"/)).toBeTruthy();expect(rescore().disabled).toBe(false);
});
it("allows retry for failed scoring and shows run-level failure text",async()=>{
  setup({...finished,state:"failed",score_state:"failed",error:{kind:"cost_missing",message:"Backend did not report cost."}} as Detail);await tick();
  expect(screen.getByText("Scoring failed. Re-score to retry.")).toBeTruthy();expect(screen.getByText("Backend did not report cost.")).toBeTruthy();expect(rescore().disabled).toBe(false);
});
it("handles missing metrics and disables rescore while the run itself is running",async()=>{
  const s=setup({...finished,state:"running"} as Detail,{report:null});await tick();
  expect(screen.getByText("Metrics missing. Re-score.")).toBeTruthy();expect(rescore().disabled).toBe(true);
});
it("continues after three poll misses, clears the banner on recovery, and supports initial Retry",async()=>{
  const s=setup({...finished,score_state:"running"} as Detail);await tick();s.miss(true);await tick(3000);
  expect(screen.getByText("Lost contact with eval server — retrying")).toBeTruthy();s.miss(false);await tick(1000);expect(screen.queryByText("Lost contact with eval server — retrying")).toBeNull();
  s.unmount();const offline=setup();offline.miss(true);await tick(0); // Initial fetch already began; force a fresh request with a new run id.
  offline.rerender(<RunDetail {...offline.props} runId="another-run"/>);await tick();
  expect(screen.getByText("Eval server not reachable")).toBeTruthy();offline.miss(false);fireEvent.click(screen.getByRole("button",{name:"Retry"}));await tick();expect(screen.queryByText("Eval server not reachable")).toBeNull();
});
it("does not overlap polls and aborts pending run and metric reads on unmount",async()=>{
  const s=setup({...finished,score_state:"running"} as Detail,{holdMetrics:true});await tick();s.holdPoll();await tick(1000);
  expect(s.pendingPolls).toHaveLength(1);expect(s.pendingReports).toHaveLength(1);
  const count=s.fetch.mock.calls.length;await tick(5000);expect(s.fetch.mock.calls.length).toBe(count);
  s.unmount();expect(s.pendingPolls[0].signal.aborted).toBe(true);expect(s.pendingReports[0].signal.aborted).toBe(true);await tick(60000);expect(s.fetch.mock.calls.length).toBe(count);
});
it("ignores late run and metric responses after changing ids",async()=>{
  const s=setup({...finished,score_state:"running"} as Detail,{holdMetrics:true});await tick();s.holdPoll();await tick(1000);
  const previousSignals=[...s.signals];
  s.rerender(<RunDetail {...s.props} runId="new-run"/>);await tick();expect(previousSignals.at(-1)?.aborted).toBe(true);
  await act(async()=>{s.releasePoll(Response.json({...finished,dataset:"stale-dataset"}));s.releaseMetrics(Response.json(metrics));});
  expect(screen.queryByRole("heading",{name:/stale-dataset/})).toBeNull();
  await act(async()=>{s.releasePoll(Response.json({...finished,run_id:"new-run",dataset:"current-dataset"}));s.releaseMetrics(Response.json(metrics));});
  expect(screen.getByRole("heading",{name:/current-dataset/})).toBeTruthy();
});

it("shows missing metrics for completed scoring and permits Re-score",async()=>{
  setup(finished as Detail,{report:null});await tick();
  expect(screen.getByText("Metrics missing. Re-score.")).toBeTruthy();expect(rescore().disabled).toBe(false);
});
it("blocks duplicate rescore clicks and aborts its POST on unmount",async()=>{
  const s=setup(finished as Detail,{holdPost:true});await tick();fireEvent.click(rescore());fireEvent.click(rescore());await tick();
  expect(s.fetch.mock.calls.filter(([url])=>String(url).endsWith("/rescore"))).toHaveLength(1);
  const signal=s.signals.at(-1)!;expect(signal.aborted).toBe(false);s.unmount();expect(signal.aborted).toBe(true);
  const count=s.fetch.mock.calls.length;await tick(60000);expect(s.fetch.mock.calls.length).toBe(count);
});
