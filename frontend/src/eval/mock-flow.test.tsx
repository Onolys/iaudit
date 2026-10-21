// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import EvalApp from "./EvalApp";
import { createEvalApi } from "./evalApi";
import datasets from "./fixtures/datasets.json";
import metadata from "./fixtures/dataset-detail.json";
import estimate from "./fixtures/estimate-unknown.json";
import finished from "./fixtures/run-finished.json";
import running from "./fixtures/run-running.json";
import report from "./fixtures/metrics.json";
import items from "./fixtures/items.json";
import saved from "./fixtures/item-ok.json";
import comparison from "./fixtures/comparison.json";
import type { RunDetail } from "./evalTypes";
const tick=async(ms=0)=>{await act(async()=>{await vi.advanceTimersByTimeAsync(ms);});};
beforeEach(()=>{localStorage.clear();vi.useFakeTimers();});
afterEach(()=>{cleanup();vi.useRealTimers();vi.unstubAllGlobals();});
function setup(active=false, resumable=false) {
  let live=(resumable ? {...running,state:"aborted",score_state:"done"} : active ? structuredClone(running) : null) as RunDetail|null;
  let hold=false;
  const pending:{signal:AbortSignal}[]=[];
  const summaries=()=>[finished,{...finished,run_id:comparison.run_b},...(live?[live]:[])].map(run=>({...run,progress:undefined,run_info:undefined,error:undefined}));
  const network=vi.fn(()=>{throw Error("Live audit calls are forbidden");});vi.stubGlobal("fetch",network);
  const fetch=vi.fn(async(url:RequestInfo|URL,opts?:RequestInit):Promise<Response>=>{
    const path=String(url);
    if(path.endsWith("/health"))return Response.json({eval_api_version:"1.0.0",backend:{url:"http://backend.invalid",reachable:true}});
    if(path.endsWith("/datasets"))return Response.json(datasets);
    if(path.includes("/datasets/"))return Response.json(metadata);
    if(path.endsWith("/estimate"))return Response.json(estimate);
    if(path.endsWith("/runs")) {
      if(opts?.method === "POST"){live={...running,run_id:"fictional-new"} as RunDetail;return Response.json({run_id:live.run_id},{status:202});}
      return Response.json(summaries());
    }
    if(path.includes("/compare?")) {
      const query=new URL(path,"http://offline.invalid").searchParams;
      return Response.json({...comparison,run_a:query.get("a"),run_b:query.get("b")});
    }
    if(path.endsWith("/resume")) {
      live={...live!,state:"running",score_state:"pending"};
      return Response.json({...live,progress:undefined,run_info:undefined,error:undefined});
    }
    const match=path.match(/\/runs\/([^/]+)(.*)/);if(!match)throw Error(`Unexpected offline URL ${path}`);
    const runId=decodeURIComponent(match[1]),suffix=match[2];
    if(suffix === "/metrics")return Response.json({...report,run_id:runId});
    if(suffix.startsWith("/items?"))return Response.json(items);
    if(suffix.startsWith("/items/"))return Response.json(saved);
    if(suffix === "") {
      if(hold)return new Promise<Response>(()=>{pending.push({signal:opts!.signal!});});
      return Response.json(live?.run_id === runId ? live : {...finished,run_id:runId});
    }
    throw Error(`Unexpected offline URL ${path}`);
  });
  render(<EvalApp api={createEvalApi({fetch:fetch as typeof globalThis.fetch})}/>);
  return {fetch,network,pending,replaceLive:(run:RunDetail)=>{live=run;},hold:(value:boolean)=>{hold=value;},finish:()=>{live={...live!,state:"finished",score_state:"done"};}};
}
const row=(id:string)=>screen.getByRole("checkbox",{name:`Select ${id}`}).closest("tr")!;
it("starts a run, inspects its saved item, returns to list, compares and returns from both A/B items",async()=>{
  const s=setup();await tick();fireEvent.click(screen.getByRole("button",{name:"Run"}));await tick();
  expect(screen.getByRole("progressbar")).toBeTruthy();s.finish();await tick(1000);
  fireEvent.click(row("fictional-new"));await tick();expect(screen.getByRole("region",{name:"Run detail"})).toBeTruthy();
  fireEvent.click(screen.getByRole("button",{name:"Public contract example"}));await tick();
  expect(screen.getByText("fictional-new - fictional-item-0")).toBeTruthy();expect(screen.getByRole("region",{name:"Gold annotations"})).toBeTruthy();
  expect(screen.queryByRole("button",{name:/Upload request/})).toBeNull();
  fireEvent.click(screen.getByRole("button",{name:"Back to run"}));await tick();
  fireEvent.click(screen.getByRole("button",{name:"Back to runs"}));await tick();
  fireEvent.click(screen.getByRole("checkbox",{name:`Select ${comparison.run_a}`}));fireEvent.click(screen.getByRole("checkbox",{name:`Select ${comparison.run_b}`}));
  fireEvent.click(screen.getByRole("button",{name:"Compare selected (2)"}));await tick();expect(screen.getByText("n shared = 2")).toBeTruthy();
  for(const [label,runId] of [["open in A",comparison.run_a],["open in B",comparison.run_b]]) {
    fireEvent.click(screen.getByRole("button",{name:label}));await tick();expect(screen.getByText(`${runId} - fictional-item-0`)).toBeTruthy();
    fireEvent.click(screen.getByRole("button",{name:"Back to comparison"}));await tick();
    expect(screen.getByText(`A: ${comparison.run_a}`)).toBeTruthy();expect(screen.getByText(`B: ${comparison.run_b}`)).toBeTruthy();
  }
  expect(s.fetch.mock.calls.some(([url])=>String(url)===`/eval-api/runs/${comparison.run_a}/items/fictional-item-0`)).toBe(true);
  expect(s.fetch.mock.calls.some(([url])=>String(url)===`/eval-api/runs/${comparison.run_b}/items/fictional-item-0`)).toBe(true);
  expect(s.network).not.toHaveBeenCalled();expect(s.fetch.mock.calls.every(([url])=>String(url).startsWith("/eval-api/"))).toBe(true);
});
it("cancels each departed progress/scoring poll and reattaches the active server run on returning to list",async()=>{
  const s=setup(true);await tick();s.hold(true);await tick(1000);expect(s.pending).toHaveLength(1);
  s.hold(false);fireEvent.click(row(running.run_id));await tick();expect(s.pending[0].signal.aborted).toBe(true);
  expect(screen.getByText("Scoring...")).toBeTruthy();s.hold(true);await tick(1000);expect(s.pending).toHaveLength(2);
  s.hold(false);fireEvent.click(screen.getByRole("button",{name:"Public contract example"}));await tick();expect(s.pending[1].signal.aborted).toBe(true);
  fireEvent.click(screen.getByRole("button",{name:"Back to run"}));await tick();fireEvent.click(screen.getByRole("button",{name:"Back to runs"}));await tick();
  expect(screen.getByRole("progressbar")).toBeTruthy();expect(within(row(running.run_id)).getByText("running")).toBeTruthy();
  const reads=()=>s.fetch.mock.calls.filter(([url])=>String(url)===`/eval-api/runs/${running.run_id}`).length;
  const before=reads();await tick(1000);expect(reads()).toBe(before+1);expect(s.network).not.toHaveBeenCalled();
});

it("clears a previous resume attachment so Back to runs follows the server's current active run",async()=>{
  const s=setup(false,true);await tick();fireEvent.click(screen.getByRole("button",{name:"Resume"}));await tick();
  expect(screen.getByRole("progressbar")).toBeTruthy();fireEvent.click(row(running.run_id));await tick();
  s.replaceLive({...running,run_id:"another-live-run"} as RunDetail);
  fireEvent.click(screen.getByRole("button",{name:"Back to runs"}));await tick();
  const panel=screen.getByRole("region",{name:"Run"});
  expect(panel.querySelector('[aria-label="Run another-live-run"]')).toBeTruthy();
  expect(within(panel).getByRole("button",{name:"Abort"})).toBeTruthy();
});
