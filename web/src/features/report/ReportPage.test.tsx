import { act, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { afterEach, describe, expect, it, vi } from "vitest";
import { sampleReport } from "../../mocks/fixtures/report";
import { mockBackend, server } from "../../mocks/server";
import { here, renderApp } from "../../test/renderApp";

const UID = "u_rater_clinic_org";
const USER = { email: "rater@clinic.org", verified: true };
const CARD = { change_goal: "Walk more in the evenings" };
const SCORED = { change_goal: "Walk more in the evenings", globals: { cct: { score: 3 } } };

/** A session at report_ready with v1 made from `rating`. */
function reported(rating: object, title?: string): string {
  const sid = mockBackend.createSession(UID, { title }).session.id;
  mockBackend.requestAudio(UID, sid, { content_type: "audio/mpeg", size_bytes: 10, filename_ext: "mp3" });
  mockBackend.completeAudio(UID, sid);
  mockBackend.settle(sid);
  mockBackend.confirmSpeaker(UID, sid, "spk_0");
  mockBackend.putRating(UID, sid, rating as never);
  mockBackend.settle(sid);
  return sid;
}

const open = (sid: string, version: string | number = 1) =>
  renderApp(`/sessions/${sid}/reports/${version}`, { user: USER });

/** Serve a hand-made report for any version (the API wraps the report in an envelope). */
function serve(report: unknown, schemaVersion = "0.0.1") {
  server.use(
    http.get("*/v1/sessions/:id/reports/:version", () =>
      HttpResponse.json({
        version: 1,
        report_id: "rep_x",
        run_id: "run_x",
        created_at: "2026-11-20T09:30:00.000Z",
        report_schema_version: schemaVersion,
        report,
      }),
    ),
  );
}
// eslint-disable-next-line @typescript-eslint/no-explicit-any
const clone = () => structuredClone(sampleReport) as unknown as Record<string, any>;

const section = (name: string) => screen.getByRole("region", { name });
const row = (name: RegExp, sec = "Scorecard") => within(section(sec)).getByRole("row", { name });

afterEach(() => {
  delete (Element.prototype as { scrollIntoView?: unknown }).scrollIntoView;
  window.location.hash = "";
});

describe("report page, rated report", () => {
  it("shows the header with run details, version select and actions", async () => {
    const sid = reported({ final: true, card: SCORED });
    open(sid);
    expect(await screen.findByText("Walk more in the evenings")).toBeInTheDocument();
    expect(screen.getAllByText(/MITI 4\.2\.1/).length).toBeGreaterThan(0);
    const details = screen.getByText(/Run details/);
    expect(details).toHaveTextContent(/mock-stt/);
    expect(details).toHaveTextContent(/default/);
    expect(details).toHaveTextContent(/mock/);
    const select = screen.getByLabelText("Version");
    expect(within(select).getAllByRole("option").map((o) => o.textContent)).toEqual([expect.stringMatching(/^v1/)]);
    expect(screen.getByRole("button", { name: "Run again" })).toBeEnabled();
    expect(screen.getByRole("button", { name: "Add or edit my rating → Run again" })).toBeInTheDocument();
  });

  it("renders sections in layout order and shows the transcript pane", async () => {
    const sid = reported({ final: true, card: SCORED });
    open(sid);
    await screen.findByRole("region", { name: "Scorecard" });
    const names = screen.getAllByRole("region").map((r) => r.getAttribute("aria-label") ?? r.querySelector("h2")?.textContent);
    expect(names).toEqual([
      "Scorecard",
      "Where Onolys disagrees",
      "Global scores",
      "Behaviour counts",
      "Summary measures",
      "Your reasons, checked",
      "Tips",
      "About this report",
      "Transcript",
    ]);
    expect(await screen.findByRole("list", { name: "Transcript" })).toBeInTheDocument();
  });

  it("scorecard chips carry text and tone", async () => {
    const sid = reported({ final: true, card: SCORED });
    open(sid);
    await screen.findByRole("region", { name: "Scorecard" });
    const cct = within(row(/Cultivating Change Talk/)).getByText("Onolys -2 (differs)");
    expect(cct).toHaveAttribute("data-tone", "differs");
    const cr = within(row(/Complex Reflection/)).getByText("Onolys +2 (flagged)");
    expect(cr).toHaveAttribute("data-tone", "flagged");
    const empathy = within(row(/Empathy/)).getByText("Onolys +1");
    expect(empathy).toHaveAttribute("data-tone", "agree");
    expect(within(row(/Partnership/)).getByText("Same as you")).toHaveAttribute("data-tone", "agree");
  });

  it("shows disagreement blocks only for a differing global and a flagged count", async () => {
    const sid = reported({ final: true, card: SCORED });
    open(sid);
    const blocks = within(await screen.findByRole("region", { name: "Where Onolys disagrees" }));
    expect(blocks.getAllByRole("article")).toHaveLength(2);
    expect(blocks.getByText("Onolys disagrees on Cultivating Change Talk, here's why")).toBeInTheDocument();
    expect(blocks.getByText("Onolys counted more complex reflections than you did")).toBeInTheDocument();
    expect(blocks.getByText(/Lines supporting your rating/)).toBeInTheDocument();
    // Simple Reflection only differs: a chip and a table row, no block.
    expect(blocks.queryByText(/Simple Reflection/)).toBeNull();
    expect(within(row(/Simple Reflection/)).getByText("Onolys -2 (differs)")).toBeInTheDocument();
  });

  it("globals, behaviour table with '+N more', summaries, tips and method", async () => {
    const sid = reported({ final: true, card: SCORED });
    open(sid);
    const globals = within(await screen.findByRole("region", { name: "Global scores" }));
    expect(globals.getByText(/Several clear statements about walking more/)).toBeInTheDocument();
    const table = within(section("Behaviour counts"));
    expect(within(table.getByRole("row", { name: /Complex Reflection/ })).getByText("+2 more")).toBeInTheDocument();
    expect(table.getByText(/can't be matched line by line/)).toBeInTheDocument();
    const summaries = within(section("Summary measures"));
    expect(summaries.getAllByText(/reference levels, not pass marks/i).length).toBeGreaterThan(0);
    expect(within(section("Tips")).getAllByRole("listitem")).toHaveLength(3);
    expect(within(section("About this report")).getByText(/not official MITI coding/i)).toBeInTheDocument();
    expect(within(section("Your reasons, checked")).getByText("Partly supported")).toBeInTheDocument();
  });

  it("clicking an instance chip selects it, scrolls and pulses it in the transcript", async () => {
    const scroll = vi.fn();
    Element.prototype.scrollIntoView = scroll;
    const sid = reported({ final: true, card: SCORED });
    open(sid);
    await screen.findByRole("list", { name: "Transcript" });
    await screen.findByRole("region", { name: "Behaviour counts" });
    const chip = within(row(/Complex Reflection/, "Behaviour counts")).getByRole("button", {
      name: /part of you still wants to get out there/,
    });
    await userEvent.click(chip);
    expect(window.location.hash).toBe("#i=cr-1");
    await waitFor(() => expect(scroll).toHaveBeenCalled());
    const mark = within(screen.getByRole("list", { name: "Transcript" })).getByText(/part of you still wants to get out there/);
    expect(mark.tagName).toBe("MARK");
    expect(mark).toHaveClass("pulse");
  });

  it("a tip quote highlights in the transcript", async () => {
    const sid = reported({ final: true, card: SCORED });
    open(sid);
    await screen.findByRole("list", { name: "Transcript" });
    const tips = within(await screen.findByRole("region", { name: "Tips" }));
    await userEvent.click(tips.getAllByRole("button", { name: /You'd like to walk more in the evenings\./ })[0]);
    expect(window.location.hash).toMatch(/^#i=/);
    await waitFor(() => expect(document.querySelector("mark.pulse")).not.toBeNull());
  });
});

describe("report page, no rating, then add a rating and run again", () => {
  it("shows Onolys only, then a rated v2 after 'Submit and run again'", async () => {
    const sid = reported({ final: true, no_rating: true, card: CARD });
    const { router } = open(sid);
    await screen.findByRole("region", { name: "Scorecard" });
    const cct = row(/Cultivating Change Talk/);
    expect(within(cct).getAllByText("–").length).toBeGreaterThan(0);
    expect(within(cct).queryByText(/differs/)).toBeNull();
    expect(screen.queryByRole("region", { name: "Where Onolys disagrees" })).toBeNull();
    expect(screen.queryByRole("region", { name: "Your reasons, checked" })).toBeNull();

    await userEvent.click(screen.getByRole("button", { name: "Add or edit my rating → Run again" }));
    const score = await screen.findByLabelText("Cultivating Change Talk score");
    await userEvent.selectOptions(score, "3");
    await userEvent.click(screen.getByRole("button", { name: "Submit and run again" }));
    await waitFor(() => expect(here(router)).toBe(`/sessions/${sid}`));

    act(() => mockBackend.settle(sid));
    await userEvent.click(await screen.findByRole("link", { name: "View report" }));
    await waitFor(() => expect(here(router)).toBe(`/sessions/${sid}/reports/2`));
    await screen.findByRole("region", { name: "Scorecard" });
    const rated = row(/Cultivating Change Talk/);
    expect(within(rated).getByText("Onolys -2 (differs)")).toBeInTheDocument(); // rated v2: chips are back
    const select = screen.getByLabelText("Version");
    expect(within(select).getAllByRole("option")).toHaveLength(2);
    expect(select).toHaveValue("2");
  });

  it("switching the version select goes to that version's route", async () => {
    const sid = reported({ final: true, no_rating: true, card: CARD });
    mockBackend.startRun(UID, sid, {});
    mockBackend.settle(sid);
    const { router } = open(sid, 2);
    const select = await screen.findByLabelText("Version");
    await userEvent.selectOptions(select, "1");
    await waitFor(() => expect(here(router)).toBe(`/sessions/${sid}/reports/1`));
  });
});

describe("report page, reasons audit failed", () => {
  it("replaces the section with a note and Run again, and keeps the rest", async () => {
    const sid = reported({ final: true, card: SCORED }, "fail-eaudit");
    const { router } = open(sid);
    const audit = within(await screen.findByRole("region", { name: "Your reasons, checked" }));
    expect(audit.getByText("We couldn't check your reasons this time. The rest of your report is complete.")).toBeInTheDocument();
    expect(within(section("Tips")).getAllByRole("listitem").length).toBeGreaterThan(0);
    expect(screen.getByRole("region", { name: "Scorecard" })).toBeInTheDocument();
    await userEvent.click(audit.getByRole("button", { name: "Run again" }));
    await waitFor(() => expect(here(router)).toBe(`/sessions/${sid}`));
  });
});

describe("report page, tolerance", () => {
  it("skips unknown sections and warns on a newer major schema_version", async () => {
    const r = clone();
    r.layout.push({ section: "future_widget", title: "Future widget" });
    serve(r, "1.2.0");
    const sid = reported({ final: true, card: SCORED });
    open(sid);
    expect(await screen.findByText(/This report was made by a newer version/)).toBeInTheDocument();
    expect(screen.getByRole("region", { name: "Scorecard" })).toBeInTheDocument();
    expect(screen.queryByText("Future widget")).toBeNull();
  });

  it("no mismatch notice for the same major, and unknown sections are skipped", async () => {
    const r = clone();
    r.layout.splice(1, 0, { section: "future_widget", title: "Future widget" });
    serve(r, "0.9.0");
    const sid = reported({ final: true, card: SCORED });
    open(sid);
    await screen.findByRole("region", { name: "Scorecard" });
    expect(screen.queryByText(/newer version/)).toBeNull();
    expect(screen.queryByText("Future widget")).toBeNull();
    expect(screen.getByRole("region", { name: "Global scores" })).toBeInTheDocument();
  });

  it("N>1 shows the value with 'based on N runs'", async () => {
    const r = clone();
    r.header.n_runs = 3;
    serve(r);
    const sid = reported({ final: true, card: SCORED });
    open(sid);
    await screen.findByRole("region", { name: "Scorecard" });
    expect(screen.getAllByText(/based on 3 runs/).length).toBeGreaterThan(0);
  });

  it("hides empty tips and shows warnings as quiet notices", async () => {
    const r = clone();
    r.tips = [];
    r.warnings = [{ code: "tips_failed" }, { code: "short_session" }];
    serve(r);
    const sid = reported({ final: true, card: SCORED });
    open(sid);
    await screen.findByRole("region", { name: "Scorecard" });
    expect(screen.queryByRole("region", { name: "Tips" })).toBeNull();
    expect(screen.getAllByRole("note").length).toBe(2);
  });

  it("renders the API's FakeEvaluation shape (no diffs, null stt and preset, scorecard only)", async () => {
    serve({
      schema_version: "0.0.1",
      created_at: "2026-11-20T09:30:00.000Z",
      header: {
        change_goal: "",
        protocol: { id: "miti", version: "4.2.1", pack_hash: "x", label: "MITI 4.2.1" },
        language: "en",
        coded_span: null,
        subject_speaker: "spk_0",
        n_runs: 1,
        models: {},
        stt: null,
        preset: null,
        code_version: "fake",
        params: {},
        has_clinician_rating: true,
        rating_coverage: { rated: 1, total: 1 },
      },
      layout: [{ section: "scorecard", title: "Scorecard" }],
      scorecard: [
        { item_id: "cct", kind: "global", label: "Cultivating Change Talk", clinician: { value: 3 }, onolys: { value: 3, mean: 3, min: 3, max: 3, values: [3] } },
      ],
      globals: [],
      behaviours: [],
      summaries: [],
      reasons_audit: { status: "ran", items: [] },
      tips: [],
      method: { statement: "Synthetic fixture report.", limits: [], not_official_miti_coding: true, citation: "n/a" },
      aggregates: {},
      warnings: [],
      run_info: {},
    });
    const sid = reported({ final: true, card: SCORED });
    open(sid);
    expect(await screen.findByRole("row", { name: /Cultivating Change Talk/ })).toBeInTheDocument();
  });

  it("a version that is not a whole number shows a not-found message", async () => {
    const sid = reported({ final: true, card: SCORED });
    open(sid, "abc");
    expect(await screen.findByText(/couldn't find that report/i)).toBeInTheDocument();
  });

  it("an unknown version shows a not-found message with a link back to the session", async () => {
    const sid = reported({ final: true, card: SCORED });
    open(sid, 9);
    expect(await screen.findByText(/couldn't find that report/i)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Back to the session" })).toHaveAttribute("href", `/sessions/${sid}`);
  });
});
