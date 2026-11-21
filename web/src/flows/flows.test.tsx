/**
 * SP05 Task 14: end-to-end flow tests (PRD R9, D12, AC2, AC9, AC10). Every flow starts at a route, drives the real
 * router and pages through user-visible steps, and MSW serves /v1 from the in-memory mock backend. The only
 * out-of-band moves are the ones the real worker does: `mockBackend.advance` stands in for transcription/run stages,
 * `service.markVerified` for clicking the email link. Page-level detail lives next to each page; these tests cover
 * the journeys across pages.
 */
import { act, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { mockBackend, server } from "../mocks/server";
import { here, renderApp } from "../test/renderApp";

const EMAIL = "rater@clinic.org";
const UID = "u_rater_clinic_org";
const USER = { email: EMAIL, verified: true };

/**
 * jsdom's XMLHttpRequest is not intercepted by MSW (and would hit the network), so the upload PUT goes through a
 * thin XHR stand-in that sends the same method, URL, headers and body with fetch, which MSW serves. The mock
 * handler pins Content-Type like the signed URL, so a wrong header still fails the upload.
 */
class FetchXhr {
  status = 0;
  onload: (() => void) | null = null;
  onerror: (() => void) | null = null;
  onabort: (() => void) | null = null;
  ontimeout: (() => void) | null = null;
  upload: { onprogress: ((e: { lengthComputable: boolean; loaded: number; total: number }) => void) | null } = { onprogress: null };
  private method = "";
  private url = "";
  private headers: Record<string, string> = {};
  private ctl = new AbortController();
  open(method: string, url: string) {
    this.method = method;
    this.url = url;
  }
  setRequestHeader(k: string, v: string) {
    this.headers[k] = v;
  }
  send(body: Blob) {
    this.upload.onprogress?.({ lengthComputable: true, loaded: body.size / 2, total: body.size });
    fetch(this.url, { method: this.method, headers: this.headers, body, signal: this.ctl.signal }).then(
      (r) => {
        this.status = r.status;
        this.upload.onprogress?.({ lengthComputable: true, loaded: body.size, total: body.size });
        this.onload?.();
      },
      () => (this.ctl.signal.aborted ? this.onabort?.() : this.onerror?.()),
    );
  }
  abort() {
    this.ctl.abort();
  }
}

beforeEach(() => {
  vi.stubGlobal("XMLHttpRequest", FetchXhr);
  // jsdom never loads media metadata; report a 15 minute recording.
  vi.stubGlobal(
    "Audio",
    class {
      duration = 15 * 60;
      onloadedmetadata: (() => void) | null = null;
      onerror: (() => void) | null = null;
      preload = "";
      set src(_: string) {
        queueMicrotask(() => this.onloadedmetadata?.());
      }
      removeAttribute() {}
    },
  );
  vi.stubGlobal("URL", Object.assign(URL, { createObjectURL: () => "blob:x", revokeObjectURL: () => {} }));
});
afterEach(() => {
  vi.unstubAllGlobals();
  server.events.removeAllListeners();
  localStorage.clear();
  sessionStorage.clear();
});

const user = () => userEvent.setup();
const h1 = (name: string) => screen.findByRole("heading", { level: 1, name });
const nav = (name: string) => within(screen.getByRole("navigation")).getByRole("link", { name });
const mp3 = () => new File([new Uint8Array(100)], "visit.mp3", { type: "audio/mpeg" });
const sessionId = (router: Parameters<typeof here>[0]) => here(router).split("/")[2]!;
const step = (sid: string) => act(() => void mockBackend.advance(sid));
const settle = (sid: string) => act(() => mockBackend.settle(sid));

/** Dashboard -> New session -> choose file -> Start; ends on /sessions/:id. */
async function uploadViaUi(u: ReturnType<typeof user>, router: Parameters<typeof here>[0], title?: string) {
  await u.click(nav("New session"));
  await h1("New session");
  if (title) await u.type(screen.getByLabelText(/title/i), title);
  await u.upload(screen.getByLabelText(/audio recording/i), mp3());
  await u.click(screen.getByRole("button", { name: /start/i }));
  await waitFor(() => expect(here(router)).toMatch(/^\/sessions\/(?!new)[^/]+$/));
  const sid = sessionId(router);
  await h1("Session");
  await waitFor(() => expect(mockBackend.getSession(UID, sid).status).not.toBe("uploading"));
  return sid;
}
/** Fill the rating card with a goal (and optionally Cultivating Change Talk) and submit it. */
async function rateViaUi(u: ReturnType<typeof user>, score?: string) {
  await u.type(await screen.findByLabelText("Change goal"), "Walk more in the evenings");
  if (score) await u.selectOptions(screen.getByLabelText("Cultivating Change Talk score"), score);
  await u.click(screen.getByRole("button", { name: "Submit rating" }));
  await screen.findByText(/Rating submitted\./);
}
/** Transcription done (worker steps), then confirm the first speaker on the gate. */
async function confirmSpeakerViaUi(u: ReturnType<typeof user>, sid: string) {
  settle(sid); // validating -> transcribing -> awaiting_input
  const list = await screen.findByRole("list", { name: "Speakers" });
  const cards = within(list).getAllByRole("listitem").filter((li) => li.parentElement === list);
  await u.click(within(cards[0]).getByRole("button", { name: "This is the clinician" }));
  await waitFor(() => expect(screen.queryByRole("list", { name: "Speakers" })).not.toBeInTheDocument());
}

describe("flow: sign-up, verify, upload, speaker + rating during transcription, report (AC2, AC9)", () => {
  it("runs end to end and Run again makes v2 with both versions in the select", async () => {
    const u = user();
    const { router, service } = renderApp("/signup");
    await h1("Sign up");
    await u.type(screen.getByLabelText("Email"), EMAIL);
    await u.type(screen.getByLabelText("Password"), "longenough1");
    await u.click(screen.getByRole("button", { name: "Create account" }));
    await h1("Verify your email");
    expect(screen.getByText(/spam/i)).toBeInTheDocument();
    expect(service.calls.verificationEmails).toBe(1);

    // not verified yet: the app stays put and explains
    await u.click(screen.getByRole("button", { name: "I've verified" }));
    expect(await screen.findByRole("status")).toHaveTextContent("haven't seen your verification");
    service.markVerified(EMAIL);
    await u.click(screen.getByRole("button", { name: "I've verified" }));
    await h1("Sessions");
    expect(screen.getByRole("link", { name: "See a sample report" })).toBeInTheDocument(); // empty state

    const sid = await uploadViaUi(u, router, "Visit 3");
    expect(screen.getByRole("status")).not.toHaveTextContent(/start the rating|limit/i);

    // rating card filled while transcription runs; a rating alone does not start the run
    expect(mockBackend.getSession(UID, sid).status).toBe("validating");
    await rateViaUi(u, "3");
    expect(mockBackend.getSession(UID, sid).flags.rating_submitted).toBe(true);
    step(sid);
    await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent(/transcrib/i));

    await confirmSpeakerViaUi(u, sid); // run starts by itself once speaker + rating are in
    await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent("Rating the session"));
    settle(sid);
    await u.click(await screen.findByRole("link", { name: "View report" }));
    await waitFor(() => expect(here(router)).toBe(`/sessions/${sid}/reports/1`));
    await h1("Report");
    const scorecard = await screen.findByRole("region", { name: "Scorecard" });
    expect(within(scorecard).getByRole("row", { name: /Cultivating Change Talk/ })).toHaveTextContent("Onolys -2 (differs)");
    expect(screen.getByRole("region", { name: "Where Onolys disagrees" })).toBeInTheDocument();

    // Run again from the report -> v2 -> version select shows both
    await u.click(screen.getByRole("button", { name: "Add or edit my rating → Run again" }));
    await u.click(await screen.findByRole("button", { name: "Submit and run again" }));
    await waitFor(() => expect(here(router)).toBe(`/sessions/${sid}`));
    settle(sid);
    await u.click(await screen.findByRole("link", { name: "View report" }));
    await waitFor(() => expect(here(router)).toBe(`/sessions/${sid}/reports/2`));
    const select = await screen.findByLabelText("Version");
    expect(within(select).getAllByRole("option")).toHaveLength(2);
    expect(select).toHaveValue("2");
  });
});

describe("flow: no-rating run, add a rating, run again (AC3)", () => {
  it("shows an Onolys-only v1, then a rated v2", async () => {
    const u = user();
    const { router } = renderApp("/", { user: USER });
    await h1("Sessions");
    const sid = await uploadViaUi(u, router);
    await confirmSpeakerViaUi(u, sid);
    await u.type(await screen.findByLabelText("Change goal"), "Walk more in the evenings");
    await u.click(screen.getByRole("button", { name: /No rating/ }));
    await screen.findByText(/Saved without a rating/);
    await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent("Rating the session"));
    settle(sid);
    await u.click(await screen.findByRole("link", { name: "View report" }));
    await h1("Report");
    const cct = within(await screen.findByRole("region", { name: "Scorecard" })).getByRole("row", { name: /Cultivating Change Talk/ });
    expect(within(cct).queryByText(/differs/)).toBeNull();
    expect(screen.queryByRole("region", { name: "Where Onolys disagrees" })).toBeNull();

    await u.click(screen.getByRole("button", { name: "Add or edit my rating → Run again" }));
    await u.selectOptions(await screen.findByLabelText("Cultivating Change Talk score"), "3");
    await u.click(screen.getByRole("button", { name: "Submit and run again" }));
    await waitFor(() => expect(here(router)).toBe(`/sessions/${sid}`));
    settle(sid);
    await u.click(await screen.findByRole("link", { name: "View report" }));
    await waitFor(() => expect(here(router)).toBe(`/sessions/${sid}/reports/2`));
    const rated = within(await screen.findByRole("region", { name: "Scorecard" })).getByRole("row", { name: /Cultivating Change Talk/ });
    expect(within(rated).getByText("Onolys -2 (differs)")).toBeInTheDocument();
  });
});

describe("flow: failure, then Run again (AC6a)", () => {
  it("shows the failure card with a reference id, Run again resumes the timeline", async () => {
    const u = user();
    const { router } = renderApp("/", { user: USER });
    await h1("Sessions");
    const sid = await uploadViaUi(u, router, "fail-paudit");
    await confirmSpeakerViaUi(u, sid);
    await rateViaUi(u);
    await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent("Rating the session"));
    settle(sid); // paudit stage fails
    const card = await screen.findByRole("alert");
    expect(card).toHaveTextContent(/something went wrong/i);
    expect(card).toHaveTextContent(`Reference: ${sid}`);
    await u.click(within(card).getByRole("button", { name: "Run again" }));
    await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent("Rating the session"));
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(mockBackend.listRuns(UID, sid)).toHaveLength(2);
  });
});

describe("flow: reasons audit failed (AC3, D17)", () => {
  it("the report carries the note with Run again and keeps the rest", async () => {
    const u = user();
    const { router } = renderApp("/", { user: USER });
    await h1("Sessions");
    const sid = await uploadViaUi(u, router, "fail-eaudit");
    await confirmSpeakerViaUi(u, sid);
    await rateViaUi(u, "3");
    settle(sid);
    await u.click(await screen.findByRole("link", { name: "View report" }));
    const audit = within(await screen.findByRole("region", { name: "Your reasons, checked" }));
    expect(audit.getByText("We couldn't check your reasons this time. The rest of your report is complete.")).toBeInTheDocument();
    expect(screen.getByRole("region", { name: "Scorecard" })).toBeInTheDocument();
    expect(screen.getByRole("region", { name: "Tips" })).toBeInTheDocument();
    await u.click(audit.getByRole("button", { name: "Run again" }));
    await waitFor(() => expect(here(router)).toBe(`/sessions/${sid}`));
    expect(mockBackend.listRuns(UID, sid)).toHaveLength(2);
  });
});

describe("flow: daily cap reached at auto-start, then Start (AC6a)", () => {
  it("says so with the reset time; Start runs once allowed", async () => {
    const u = user();
    const { router } = renderApp("/", { user: USER });
    await h1("Sessions");
    const sid = await uploadViaUi(u, router, "cap-held");
    await rateViaUi(u);
    await confirmSpeakerViaUi(u, sid);
    await waitFor(() =>
      expect(screen.getByRole("status")).toHaveTextContent(/You've reached today's limit\. You can start the rating after .+\./),
    );
    expect(mockBackend.listRuns(UID, sid)).toHaveLength(0);
    await u.click(screen.getByRole("button", { name: "Start" }));
    await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent("Rating the session"));
    settle(sid);
    await u.click(await screen.findByRole("link", { name: "View report" }));
    await waitFor(() => expect(here(router)).toBe(`/sessions/${sid}/reports/1`));
  });
});

describe("flow: delete a session (AC2)", () => {
  it("dashboard -> session -> confirm delete -> dashboard without it", async () => {
    const u = user();
    const sid = mockBackend.createSession(UID, { title: "Doomed visit" }).session.id;
    const { router } = renderApp("/", { user: USER });
    await u.click(await screen.findByRole("link", { name: /Doomed visit/ }));
    await h1("Session");
    expect(here(router)).toBe(`/sessions/${sid}`);
    await u.click(await screen.findByRole("button", { name: "Delete session" }));
    await u.click(within(await screen.findByRole("dialog")).getByRole("button", { name: "Delete permanently" }));
    await h1("Sessions");
    expect(here(router)).toBe("/");
    await screen.findByText(/no sessions|upload|New session/i);
    expect(screen.queryByRole("link", { name: /Doomed visit/ })).toBeNull();
    expect(() => mockBackend.getSession(UID, sid)).toThrow();
  });
});

describe("flow: API key is shown once (AC7)", () => {
  it("secret visible in the modal only; gone after Done and after leaving and coming back; not stored or logged", async () => {
    const u = user();
    const spies = (["log", "info", "warn", "error", "debug"] as const).map((m) => vi.spyOn(console, m).mockImplementation(() => {}));
    try {
      renderApp("/", { user: USER });
      await h1("Sessions");
      await u.click(nav("Settings"));
      await h1("Settings");
      await u.click(await screen.findByRole("button", { name: "Create API key" }));
      const dialog = await screen.findByRole("dialog");
      const secret = (await within(dialog).findByTestId("api-secret")).textContent ?? "";
      expect(secret).toMatch(/^onolys_[A-Za-z0-9]+_[A-Za-z0-9]+$/);
      await u.click(within(dialog).getByRole("checkbox", { name: /i've stored it/i }));
      await u.click(within(dialog).getByRole("button", { name: "Done" }));
      expect(screen.queryByRole("dialog")).toBeNull();
      expect(document.body.textContent).not.toContain(secret);

      await u.click(nav("Sessions"));
      await h1("Sessions");
      await u.click(nav("Settings"));
      await h1("Settings");
      expect(await screen.findByText(/active/i)).toBeInTheDocument();
      expect(document.body.textContent).not.toContain(secret);
      expect(JSON.stringify({ l: { ...localStorage }, s: { ...sessionStorage } })).not.toContain(secret);
      expect(JSON.stringify(spies.flatMap((s) => s.mock.calls))).not.toContain(secret);
    } finally {
      spies.forEach((s) => s.mockRestore());
    }
  });
});

describe("flow: sample report works with no network (AC3a)", () => {
  it("login -> Sample report renders the report and transcript, with zero requests", async () => {
    const u = user();
    const requests: string[] = [];
    server.events.on("request:start", ({ request }) => void requests.push(request.url));
    const { router } = renderApp("/login");
    await h1("Log in");
    await u.click(nav("Sample report"));
    await h1("Sample report");
    expect(here(router)).toBe("/sample-report");
    expect(await screen.findByRole("region", { name: "Scorecard" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /run again/i })).toBeNull();
    expect(requests).toEqual([]);
  });
});

