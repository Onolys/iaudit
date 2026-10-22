// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import EvalApp from "./EvalApp";
import { createEvalApi } from "./evalApi";
import running from "./fixtures/run-running.json";
import datasets from "./fixtures/datasets.json";
import metadata from "./fixtures/dataset-detail.json";
import estimate from "./fixtures/estimate-unknown.json";
import comparison from "./fixtures/comparison.json";
import metrics from "./fixtures/metrics.json";
import items from "./fixtures/items.json";
import type { RunDetail } from "./evalTypes";
const tick=async(ms=0)=>{await act(async()=>{await vi.advanceTimersByTimeAsync(ms);});};
beforeEach(()=>{localStorage.clear();vi.useFakeTimers();});
afterEach(()=>{cleanup();vi.useRealTimers();});
function setup() {
  let run={...running,state:"aborted",totals:{cost_usd:null,failures:0}} as RunDetail;
  let release: (()=>void)|null=null;
  let hold=false;
  let holdResume=false;
  const fetch=vi.fn(async(url:RequestInfo|URL,opts?:RequestInit):Promise<Response>=>{
    const path=String(url);
    if(path.endsWith("/health")) return Response.json({eval_api_version:"1.0.0",backend:{url:"http://backend.invalid",reachable:true}});
    if(path.endsWith("/datasets")) return Response.json(datasets);
    if(path.includes("/datasets/")) return Response.json(metadata);
    if(path.endsWith("/estimate")) return Response.json(estimate);
    if(path.includes("/compare?")) return Response.json({...comparison,run_a:running.run_id,run_b:"other-aborted"});
    if(path.endsWith("/metrics")) return Response.json(metrics);
    if(path.includes("/items?")) return Response.json(items);
    if(path.endsWith("/resume") || path.endsWith("/runs") && opts?.method === "POST") {
      if (holdResume) await new Promise<void>(done=>{release=done;});
      run={...run,state:"running"};
      return path.endsWith("/resume") ? Response.json({...run,progress:undefined,run_info:undefined}) : Response.json({run_id:run.run_id},{status:202});
    }
    if(path.endsWith("/runs")) return Response.json([{...run,progress:undefined,run_info:undefined}, {...run,run_id:"other-aborted",state:"aborted",progress:undefined,run_info:undefined}]);
    if(path.endsWith(`/runs/${running.run_id}`)) {
      if(hold) await new Promise<void>(done=>{release=done;});
      return Response.json(run);
    }
    throw Error(`Unexpected offline request ${path}`);
  });
  render(<EvalApp api={createEvalApi({fetch:fetch as typeof globalThis.fetch})}/>);
  return {fetch,setRun:(value:RunDetail)=>{run=value;},hold:()=>{hold=true;},holdResume:()=>{holdResume=true;},release:()=>{hold=false;holdResume=false;release!();}};
}
it("resumes into the single poller, disables Resume before first response, shares progress and refetches terminal",async()=>{
  const s=setup();await tick();s.hold();
  fireEvent.click(screen.getAllByRole("button",{name:"Resume"})[0]); await tick();
  for(const button of screen.getAllByRole("button",{name:"Resume"})) expect((button as HTMLButtonElement).disabled).toBe(true);
  const polls=()=>s.fetch.mock.calls.filter(([url])=>String(url).endsWith(`/runs/${running.run_id}`)).length;
  expect(polls()).toBe(1);
  await act(async()=>s.release()); await tick();
  s.setRun({...running,progress:{done:2,total:3,cost_usd:0.42,failures:1},totals:{cost_usd:0.42,failures:1}} as RunDetail);
  await tick(1000);expect(polls()).toBe(2);
  const row=screen.getByRole("checkbox",{name:`Select ${running.run_id}`}).closest("tr")!;
  expect(within(row).getByText("$0.42")).toBeTruthy();expect(within(row).getByText("1")).toBeTruthy();
  const lists=s.fetch.mock.calls.filter(([url])=>String(url).endsWith("/runs")).length;
  s.setRun({...running,state:"finished"} as RunDetail);await tick(1000);
  expect(s.fetch.mock.calls.filter(([url])=>String(url).endsWith("/runs")).length).toBe(lists+1);
  await tick(5000);expect(polls()).toBe(3);
});
it("disables Resume while a newly started run awaits its first poll",async()=>{
  const s=setup();await tick();await tick(400);s.hold();fireEvent.click(screen.getByRole("button",{name:"Run"}));await tick();
  for(const button of screen.getAllByRole("button",{name:"Resume"})) expect((button as HTMLButtonElement).disabled).toBe(true);
});
it("opens run detail from a row",async()=>{
  setup();await tick();
  fireEvent.click(screen.getByRole("checkbox",{name:`Select ${running.run_id}`}).closest("tr")!);
  await tick();expect(screen.getByRole("region",{name:"Run detail"})).toBeTruthy();
});

it("opens comparison with the two selected identifiers",async()=>{
  setup();await tick();
  fireEvent.click(screen.getByRole("checkbox",{name:`Select ${running.run_id}`}));
  fireEvent.click(screen.getByRole("checkbox",{name:"Select other-aborted"}));
  fireEvent.click(screen.getByRole("button",{name:"Compare selected (2)"}));
  await tick();expect(screen.getByRole("heading",{name:"Compare runs"})).toBeTruthy();
  expect(screen.getByText(`A: ${running.run_id}`)).toBeTruthy();expect(screen.getByText("B: other-aborted")).toBeTruthy();
});
it("restarts polling when the same run is resumed again after a terminal result",async()=>{
  const s=setup();await tick();
  const resume=()=>fireEvent.click(within(screen.getByRole("checkbox",{name:`Select ${running.run_id}`}).closest("tr")!).getByRole("button",{name:"Resume"}));
  resume();await tick();s.setRun({...running,state:"aborted"} as RunDetail);await tick(1000);
  const polls=()=>s.fetch.mock.calls.filter(([url])=>String(url).endsWith(`/runs/${running.run_id}`)).length;
  expect(polls()).toBe(2);resume();await tick();expect(polls()).toBe(3);
  expect(screen.getByRole("button",{name:"Abort"})).toBeTruthy();await tick(1000);expect(polls()).toBe(4);
});

it("blocks starting a different run while Resume POST is in flight",async()=>{
  const s=setup();await tick();s.holdResume();
  fireEvent.click(screen.getAllByRole("button",{name:"Resume"})[0]);await tick();
  const run=screen.getByRole("button",{name:"Run"}) as HTMLButtonElement;
  expect(run.disabled).toBe(true);fireEvent.click(run);
  expect(s.fetch.mock.calls.filter(([url,opts])=>String(url).endsWith("/runs") && opts?.method === "POST")).toHaveLength(0);
  await act(async()=>s.release());await tick();expect(screen.getByRole("progressbar")).toBeTruthy();
});
