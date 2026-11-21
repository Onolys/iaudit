// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import App from "../App";
import { getConfig } from "../config";
import { defaultRegistry } from "../transport/mock/registry";
import type { AuditDeps } from "../transport/runAudit";
import PauditApp from "./PauditApp";
import sample from "./fixtures/sample-result.json";
import transcript from "./fixtures/good_practice.transcript.json";
import params from "./fixtures/good_practice.params.json";

const SECRET = "ZEBRA-UNIQUE-PHRASE-9931";
const secretTranscript = JSON.stringify({
  language: "en",
  turns: [
    { id: "t1", speaker: "S1", text: `Hello ${SECRET}`, start_ms: 0, end_ms: 1000 },
    { id: "t2", speaker: "S2", text: "Right.", start_ms: 1000, end_ms: 2000 },
  ],
});

function deps(over: Partial<AuditDeps> & { mock?: boolean } = {}): AuditDeps {
  const { mock = true, ...rest } = over;
  return { fetch: vi.fn() as unknown as typeof fetch, config: { ...getConfig(), mock, auditUrl: "http://api.test/v1/audit" },
    registry: defaultRegistry, mockDelayMs: 0, ...rest };
}
const jsonRes = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });

const postCalls = (f: typeof fetch) => (f as unknown as ReturnType<typeof vi.fn>).mock.calls.filter(c => c[1]?.method === "POST");

beforeEach(() => localStorage.clear());
afterEach(() => { cleanup(); vi.restoreAllMocks(); });

const paste = (text: string) => fireEvent.change(screen.getByLabelText("Transcript JSON"), { target: { value: text } });
const goal = (text: string) => fireEvent.change(screen.getByLabelText("Change goal"), { target: { value: text } });
const run = () => fireEvent.click(screen.getByRole("button", { name: "Run" }));

describe("PauditApp form", () => {
  it("has the pack default, a PHI note and is mapped as the paudit view", () => {
    render(<PauditApp deps={deps()} />);
    expect((screen.getByLabelText("Pack") as HTMLInputElement).value).toBe("miti@4.2.1");
    expect(screen.getByText(/Do not paste real PHI until a BAA is in place/)).toBeTruthy();
    expect(screen.getByTestId("paudit-view")).toBeTruthy();
  });

  it("is reachable from the paudit tab of App", () => {
    render(<App deps={deps()} />);
    fireEvent.click(screen.getByRole("button", { name: "paudit" }));
    expect(screen.getByLabelText("Transcript JSON")).toBeTruthy();
  });

  it("speaker dropdown lists the transcript's speakers", () => {
    render(<PauditApp deps={deps()} />);
    paste(secretTranscript);
    const sel = screen.getByLabelText("Clinician speaker") as HTMLSelectElement;
    expect([...sel.options].map(o => o.value).filter(Boolean)).toEqual(["S1", "S2"]);
  });

  it("Load fixture prefills transcript, speaker, goal", async () => {
    render(<PauditApp deps={deps()} />);
    fireEvent.click(screen.getByRole("button", { name: "Load fixture" }));
    await waitFor(() => expect((screen.getByLabelText("Change goal") as HTMLInputElement).value).toBe(params.change_goal));
    expect((screen.getByLabelText("Clinician speaker") as HTMLSelectElement).value).toBe(params.speaker_map.subject);
    expect((screen.getByLabelText("Transcript JSON") as HTMLTextAreaElement).value).toContain(transcript.turns[0].text);
  });

  it("required fields block Run: no request, errors shown", async () => {
    const d = deps({ mock: false });
    render(<PauditApp deps={d} />);
    run();
    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toMatch(/transcript/i);
    paste(secretTranscript);
    run();
    expect((await screen.findByRole("alert")).textContent).toMatch(/clinician speaker/i);
    fireEvent.change(screen.getByLabelText("Clinician speaker"), { target: { value: "S1" } });
    run();
    expect((await screen.findByRole("alert")).textContent).toMatch(/change goal/i);
    expect(postCalls(d.fetch)).toHaveLength(0);
    expect(screen.queryByRole("region", { name: "Warnings" })).toBeNull();
  });

  it("invalid JSON, half a span and a bad n_runs also block Run", async () => {
    const d = deps({ mock: false });
    render(<PauditApp deps={d} />);
    paste("{not json");
    run();
    expect((await screen.findByRole("alert")).textContent).toMatch(/not valid JSON/i);
    paste(secretTranscript);
    fireEvent.change(screen.getByLabelText("Clinician speaker"), { target: { value: "S1" } });
    goal("g");
    fireEvent.change(screen.getByLabelText("Span from (s)"), { target: { value: "10" } });
    run();
    expect((await screen.findByRole("alert")).textContent).toMatch(/span/i);
    fireEvent.change(screen.getByLabelText("Span from (s)"), { target: { value: "" } });
    fireEvent.change(screen.getByLabelText("Runs (n_runs)"), { target: { value: "9" } });
    run();
    expect((await screen.findByRole("alert")).textContent).toMatch(/n_runs/);
    expect(postCalls(d.fetch)).toHaveLength(0);
  });
});

describe("PauditApp run", () => {
  it("mock mode: Run shows the sample result and sends nothing", async () => {
    const d = deps();
    render(<PauditApp deps={d} />);
    fireEvent.click(screen.getByRole("button", { name: "Load fixture" }));
    await waitFor(() => expect((screen.getByLabelText("Change goal") as HTMLInputElement).value).not.toBe(""));
    run();
    expect(await screen.findByRole("table", { name: "Utterances" })).toBeTruthy();
    expect(screen.getByRole("table", { name: "Summary scores" })).toBeTruthy();
    expect(d.fetch).not.toHaveBeenCalled();
  });

  it("live: posts through the injected fetch with the contract body and shows the result", async () => {
    const f = vi.fn(async () => jsonRes(sample)) as unknown as typeof fetch;
    render(<PauditApp deps={deps({ mock: false, fetch: f })} />);
    paste(secretTranscript);
    fireEvent.change(screen.getByLabelText("Clinician speaker"), { target: { value: "S1" } });
    goal("walk more");
    fireEvent.change(screen.getByLabelText("Runs (n_runs)"), { target: { value: "3" } });
    fireEvent.change(screen.getByLabelText("Span from (s)"), { target: { value: "0" } });
    fireEvent.change(screen.getByLabelText("Span to (s)"), { target: { value: "600" } });
    run();
    expect(await screen.findByRole("table", { name: "Utterances" })).toBeTruthy();
    const call = (f as unknown as ReturnType<typeof vi.fn>).mock.calls.find(c => c[1]?.method === "POST")!;
    expect(call[0]).toBe("http://api.test/v1/paudit");
    const body = JSON.parse(call[1].body);
    expect(body.pack).toBe("miti@4.2.1");
    expect(body.params).toEqual({ speaker_map: { subject: "S1" }, change_goal: "walk more", coded_span: { from_s: 0, to_s: 600 }, n_runs: 3 });
    expect(body.transcript.turns).toHaveLength(2);
  });

  it("shows the server's error message for a rejected run", async () => {
    const err = { schema_version: "0.0.2", status: 502, message: "The protocol audit failed.", details: [{ code: "run_failed", message: "Every run failed." }] };
    const f = vi.fn(async () => jsonRes(err, 502)) as unknown as typeof fetch;
    render(<PauditApp deps={deps({ mock: false, fetch: f })} />);
    paste(secretTranscript);
    fireEvent.change(screen.getByLabelText("Clinician speaker"), { target: { value: "S1" } });
    goal("g");
    run();
    const alert = await screen.findByRole("alert");
    expect(within(alert).getByText(/The protocol audit failed/)).toBeTruthy();
    expect(within(alert).getByText(/run_failed/)).toBeTruthy();
  });

  it("transcript text never reaches the URL, storage or console", async () => {
    const spies = (["log", "info", "warn", "error", "debug"] as const).map(m => vi.spyOn(console, m).mockImplementation(() => {}));
    const setItem = vi.spyOn(Storage.prototype, "setItem");
    const f = vi.fn(async () => jsonRes({ schema_version: "0.0.2", status: 502, message: "The protocol audit failed.", details: [{ code: "run_failed", message: "x" }] }, 502)) as unknown as typeof fetch;
    const pushState = vi.spyOn(history, "pushState");
    const replaceState = vi.spyOn(history, "replaceState");
    render(<PauditApp deps={deps({ mock: false, fetch: f })} />);
    paste(secretTranscript);
    fireEvent.change(screen.getByLabelText("Clinician speaker"), { target: { value: "S1" } });
    goal("g");
    run();
    await screen.findByRole("alert");
    // the secret appears only in the POST body
    const calls = (f as unknown as ReturnType<typeof vi.fn>).mock.calls;
    for (const c of calls) expect(String(c[0])).not.toContain(SECRET);
    expect(window.location.href).not.toContain(SECRET);
    expect(decodeURIComponent(window.location.href)).not.toContain("ZEBRA");
    expect(pushState).not.toHaveBeenCalled();
    expect(replaceState).not.toHaveBeenCalled();
    expect(setItem).not.toHaveBeenCalled();
    expect(JSON.stringify({ ...localStorage })).not.toContain(SECRET);
    expect(JSON.stringify({ ...sessionStorage })).not.toContain(SECRET);
    for (const s of spies) expect(JSON.stringify(s.mock.calls)).not.toContain(SECRET);
  });
});
