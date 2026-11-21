import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";
import { mockBackend, server } from "../../mocks/server";
import { here, renderApp } from "../../test/renderApp";

const UID = "u_rater_clinic_org";
const USER = { email: "rater@clinic.org", verified: true };

const create = (title?: string) => mockBackend.createSession(UID, { title }).session.id;
const upload = (sid: string) => {
  mockBackend.requestAudio(UID, sid, { content_type: "audio/mpeg", size_bytes: 10, filename_ext: "mp3" });
  mockBackend.completeAudio(UID, sid);
};
const main = () => within(screen.getByRole("main"));
const rowOf = (name: RegExp | string) => main().getByRole("link", { name }).closest("li") as HTMLElement;

const item = (id: string, status: string, extra: object = {}) => ({
  id,
  title: `Session ${id}`,
  status,
  created_at: "2026-11-18T10:00:00.000Z",
  latest_report_version: null,
  error_code: null,
  ...extra,
});

describe("dashboard: session list", () => {
  it("shows a status chip for every state, each row linking to the session", async () => {
    const cases: [string, string][] = [
      ["created", "Uploading"],
      ["uploading", "Uploading"],
      ["validating", "Checking audio"],
      ["transcribing", "Transcribing"],
      ["awaiting_input", "Needs your input"],
      ["running", "Rating"],
      ["report_ready", "Report ready"],
      ["failed", "Failed"],
      ["deleting", "Deleting"],
    ];
    server.use(
      http.get("*/v1/sessions", () =>
        HttpResponse.json({ items: cases.map(([s], i) => item(`s${i}`, s, s === "report_ready" ? { latest_report_version: 2 } : {})) }),
      ),
    );
    renderApp("/", { user: USER });
    for (const [i, [, label]] of cases.entries()) {
      const li = await waitFor(() => rowOf(`Session s${i}`));
      expect(within(li).getByText(label)).toBeInTheDocument();
      expect(within(li).getByRole("link", { name: `Session s${i}` })).toHaveAttribute("href", `/sessions/s${i}`);
    }
  });

  it("links in-flight and failed rows to the session and Report vN straight to the report", async () => {
    server.use(
      http.get("*/v1/sessions", () =>
        HttpResponse.json({
          items: [
            item("run1", "running"),
            item("bad1", "failed", { error_code: "internal_error" }),
            item("ok1", "report_ready", { latest_report_version: 3 }),
          ],
        }),
      ),
    );
    const user = userEvent.setup();
    const { router } = renderApp("/", { user: USER });
    expect(await main().findByRole("link", { name: "Session run1" })).toHaveAttribute("href", "/sessions/run1");
    expect(main().getByRole("link", { name: "Session bad1" })).toHaveAttribute("href", "/sessions/bad1");
    expect(within(rowOf("Session run1")).queryByRole("link", { name: /Report v/ })).toBeNull();
    const rep = within(rowOf("Session ok1")).getByRole("link", { name: "Report v3" });
    expect(rep).toHaveAttribute("href", "/sessions/ok1/reports/3");
    await user.click(rep);
    expect(here(router)).toBe("/sessions/ok1/reports/3");
  });

  it("uses the date when a session has no title", async () => {
    server.use(http.get("*/v1/sessions", () => HttpResponse.json({ items: [item("x1", "failed", { title: null })] })));
    renderApp("/", { user: USER });
    const link = await main().findByRole("link", { name: /Nov 18, 2026/ });
    expect(link).toHaveAttribute("href", "/sessions/x1");
  });

  it("pages with Load more until next_cursor runs out", async () => {
    const user = userEvent.setup();
    for (let i = 1; i <= 23; i++) create(`S${String(i).padStart(2, "0")}`);
    const calls: string[] = [];
    server.events.on("request:start", ({ request }) => {
      const u = new URL(request.url);
      if (u.pathname.endsWith("/v1/sessions")) calls.push(u.search);
    });
    renderApp("/", { user: USER });
    await main().findByRole("link", { name: "S23" });
    expect(main().getAllByRole("listitem")).toHaveLength(20);
    expect(main().queryByRole("link", { name: "S03" })).toBeNull();
    await user.click(main().getByRole("button", { name: "Load more" }));
    await main().findByRole("link", { name: "S01" });
    expect(main().getAllByRole("listitem")).toHaveLength(23);
    expect(main().queryByRole("button", { name: "Load more" })).toBeNull();
    expect(calls[1]).toContain("cursor=20");
    server.events.removeAllListeners();
  });

  it("shows the usage line and a New session link", async () => {
    const sid = create("A");
    upload(sid);
    renderApp("/", { user: USER });
    expect(await main().findByText("0 of 20 runs today")).toBeInTheDocument();
    expect(main().getByRole("link", { name: "New session" })).toHaveAttribute("href", "/sessions/new");
  });

  it("over the cap: says so with the reset time", async () => {
    server.use(
      http.get("*/v1/usage", () =>
        HttpResponse.json({ runs_today: 20, daily_cap: 20, resets_at: "2026-11-21T00:00:00.000Z" }),
      ),
      http.get("*/v1/sessions", () => HttpResponse.json({ items: [item("a", "report_ready", { latest_report_version: 1 })] })),
    );
    renderApp("/", { user: USER });
    expect(await main().findByText("20 of 20 runs today")).toBeInTheDocument();
    expect(main().getByText(/reached today's limit/i)).toHaveTextContent(/after .+/);
  });

  it("shows an error with Try again when the list fails", async () => {
    let fail = true;
    server.use(
      http.get("*/v1/sessions", () =>
        fail
          ? HttpResponse.json(
              { schema_version: "0.0.1", status: 500, message: "x", details: [{ code: "internal_error", message: "x" }], request_id: "r" },
              { status: 500 },
            )
          : HttpResponse.json({ items: [item("z", "running")] }),
      ),
    );
    const user = userEvent.setup();
    renderApp("/", { user: USER });
    const btn = await main().findByRole("button", { name: "Try again" });
    fail = false;
    await user.click(btn);
    expect(await main().findByRole("link", { name: "Session z" })).toBeInTheDocument();
  });
});

describe("dashboard: empty state", () => {
  it("explains Onolys in one line and offers New session and a sample report", async () => {
    const user = userEvent.setup();
    const { router } = renderApp("/", { user: USER });
    expect(await main().findByText(/Onolys .*MITI/i)).toBeInTheDocument();
    expect(main().getByRole("link", { name: "New session" })).toHaveAttribute("href", "/sessions/new");
    await user.click(main().getByRole("link", { name: "See a sample report" }));
    expect(here(router)).toBe("/sample-report");
  });
});
