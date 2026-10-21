// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { RunsList } from "./RunsList";
import { createEvalApi } from "./evalApi";
import fixtures from "./fixtures/runs.json";
import type { RunSummary } from "./evalTypes";
afterEach(cleanup);
const rows = fixtures as RunSummary[];
function setup(data = rows.filter(row => row.state !== "running")) {
  let current = data;
  const onResume = vi.fn(), onOpenRun = vi.fn(), onCompare = vi.fn();
  const fetch = vi.fn(async (url: RequestInfo | URL) => String(url).endsWith("/resume")
    ? Response.json({...rows[2],state:"running"}) : Response.json(current));
  const api = createEvalApi({fetch: fetch as typeof globalThis.fetch});
  const props = {api,onResume,onOpenRun,onCompare};
  return {...render(<RunsList {...props} />),props,fetch,onResume,onOpenRun,onCompare,setRows:(v:RunSummary[])=>{current=v;}};
}
it("renders every column, nullable values and the cost-cap label", async () => {
  setup(); await screen.findByText("aborted: cost cap");
  for (const name of ["Select","Date","Dataset","Split","N","Schema","State","Cost","Failures"]) expect(screen.getByRole("columnheader",{name})).toBeTruthy();
  const row=screen.getByRole("checkbox",{name:"Select fictional-aborted"}).closest("tr")!;
  expect(within(row).getByText("fixture-created")).toBeTruthy(); expect(within(row).getByText("1.2.0")).toBeTruthy();
  expect(within(row).getByText("—")).toBeTruthy(); expect(within(row).getByText("3")).toBeTruthy();
});
it("implements the complete resume matrix and attaches the returned run", async () => {
  const s=setup(); await screen.findByText("aborted: cost cap");
  for(const row of rows.filter(row=>row.state!=="running")) {
    const tr=screen.getByRole("checkbox",{name:`Select ${row.run_id}`}).closest("tr")!;
    expect(within(tr).queryByRole("button",{name:"Resume"}) !== null).toBe(["aborted","aborted_cost","interrupted","failed"].includes(row.state) || row.state === "finished" && row.totals.failures>0);
  }
  fireEvent.click(screen.getAllByRole("button",{name:"Resume"})[0]); await waitFor(()=>expect(s.onResume).toHaveBeenCalledWith(expect.objectContaining({run_id:"fictional-aborted",state:"running"})));
  expect(s.onOpenRun).not.toHaveBeenCalled();
});
it("disables every resume while the server list has an active run", async()=>{
  setup(rows); await screen.findByText("aborted: cost cap");
  for(const button of screen.getAllByRole("button",{name:"Resume"})) expect((button as HTMLButtonElement).disabled).toBe(true);
});
it("limits selection to two matching datasets, supports deselect, and compares without opening a row",async()=>{
  const s=setup(); await screen.findByText("aborted: cost cap");
  const box=(id:string)=>screen.getByRole("checkbox",{name:`Select ${id}`}) as HTMLInputElement;
  fireEvent.click(box("fictional-aborted")); expect(box("fictional-other-dataset").disabled).toBe(true);
  expect((screen.getByRole("button",{name:"Compare selected (1)"}) as HTMLButtonElement).disabled).toBe(true);
  fireEvent.click(box("fictional-failed")); expect(box("fictional-interrupted").disabled).toBe(true); expect(box("fictional-aborted").disabled).toBe(false);
  fireEvent.click(screen.getByRole("button",{name:"Compare selected (2)"})); expect(s.onCompare).toHaveBeenCalledWith("fictional-aborted","fictional-failed"); expect(s.onOpenRun).not.toHaveBeenCalled();
  fireEvent.click(box("fictional-aborted")); fireEvent.click(box("fictional-failed")); expect(box("fictional-other-dataset").disabled).toBe(false);
  fireEvent.click(box("fictional-aborted").closest("tr")!); expect(s.onOpenRun).toHaveBeenCalledWith("fictional-aborted");
});
it("fetches on signal and manual refresh and explains empty results",async()=>{
  const s=setup([]); await screen.findByText("No runs yet. Start one above."); s.setRows([rows[1]]);
  s.rerender(<RunsList {...s.props} refreshKey={1}/>); await screen.findByRole("checkbox",{name:"Select fictional-finished"});
  s.setRows([]); fireEvent.click(screen.getByRole("button",{name:"Refresh"})); await screen.findByText("No runs yet. Start one above."); expect(s.fetch).toHaveBeenCalledTimes(3);
});
it("aborts a pending resume on unmount",async()=>{
  let signal: AbortSignal | null | undefined;
  const api=createEvalApi({fetch:async (url,opts)=>{
    if(String(url).endsWith("/resume")){signal=opts?.signal;return new Promise<Response>(()=>{});}
    return Response.json([rows[2]]);
  }});
  const s=render(<RunsList api={api} onResume={vi.fn()} onOpenRun={vi.fn()} onCompare={vi.fn()}/>);
  await screen.findByRole("button",{name:"Resume"}); fireEvent.click(screen.getByRole("button",{name:"Resume"}));
  await act(async()=>{}); expect(signal?.aborted).toBe(false); s.unmount(); expect(signal?.aborted).toBe(true);
});
it("drops a stale in-flight list refresh when Resume succeeds",async()=>{
  let listCalls=0;
  let finish!: (response:Response)=>void;
  let staleSignal: AbortSignal | null | undefined;
  const onResume=vi.fn();
  const api=createEvalApi({fetch:async(url,opts)=>{
    if(String(url).endsWith("/resume")) return Response.json({...rows[2],state:"running"});
    listCalls++;
    if(listCalls===1)return Response.json([rows[2],rows[4]]);
    staleSignal=opts?.signal;
    return new Promise<Response>(resolve=>{finish=resolve;});
  }});
  render(<RunsList api={api} onResume={onResume} onOpenRun={vi.fn()} onCompare={vi.fn()}/>);
  await screen.findAllByRole("button",{name:"Resume"});fireEvent.click(screen.getByRole("button",{name:"Refresh"}));
  fireEvent.click(screen.getAllByRole("button",{name:"Resume"})[0]);
  await waitFor(()=>expect(onResume).toHaveBeenCalledTimes(1));expect(staleSignal?.aborted).toBe(true);
  await act(async()=>finish(Response.json([rows[2],rows[4]])));
  expect(screen.getByText("running")).toBeTruthy();
  expect((screen.getByRole("button",{name:"Resume"}) as HTMLButtonElement).disabled).toBe(true);
});
it("sends only one resume POST for quick repeated clicks",async()=>{
  let posts=0;
  const api=createEvalApi({fetch:async(url)=>{
    if(String(url).endsWith("/resume")){posts++;return new Promise<Response>(()=>{});}
    return Response.json([rows[2],rows[4]]);
  }});
  render(<RunsList api={api} onResume={vi.fn()} onOpenRun={vi.fn()} onCompare={vi.fn()}/>);
  const buttons=await screen.findAllByRole("button",{name:"Resume"});
  fireEvent.click(buttons[0]);fireEvent.click(buttons[1]);expect(posts).toBe(1);
});
