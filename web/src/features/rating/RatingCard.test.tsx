import { cleanup, fireEvent, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { mockBackend } from "../../mocks/server";
import { renderApp } from "../../test/renderApp";

const EMAIL = "rater@clinic.org";
const UID = "u_rater_clinic_org";
const USER = { email: EMAIL, verified: true };

interface Put {
  body: { final: boolean; no_rating?: boolean; card: Record<string, unknown> };
  keepalive: boolean;
}
let puts: Put[] = [];
let pending: Promise<void>[] = [];
beforeEach(() => {
  puts = [];
  pending = [];
  // Spy above msw: the interceptor rebuilds requests, so `keepalive` is only visible here.
  const real = globalThis.fetch;
  vi.spyOn(globalThis, "fetch").mockImplementation((input, init) => {
    if (input instanceof Request && input.method === "PUT" && new URL(input.url).pathname.endsWith("/rating")) {
      const keepalive = input.keepalive;
      pending.push(input.clone().json().then((body) => void puts.push({ body, keepalive })));
    }
    return real(input, init);
  });
});
afterEach(() => vi.restoreAllMocks());

const newSession = () => mockBackend.createSession(UID, {}).session.id;
const open = async (sid: string) => {
  const view = renderApp(`/sessions/${sid}`, { user: USER });
  await screen.findByLabelText("Change goal");
  return view;
};
const flags = (sid: string) => mockBackend.getSession(UID, sid);
const setValue = (label: string | RegExp, value: string) => fireEvent.change(screen.getByLabelText(label), { target: { value } });

describe("rating card: layout", () => {
  it("shows the goal, span, four globals, ten codes and a separate notes box that is not parsed", async () => {
    await open(newSession());
    expect(screen.getByLabelText("Change goal")).toBeInTheDocument();
    expect(screen.getByLabelText(/coded from/i)).toBeInTheDocument();
    for (const g of ["Cultivating Change Talk", "Softening Sustain Talk", "Partnership", "Empathy"]) {
      expect(screen.getByLabelText(`${g} score`)).toBeInTheDocument();
      expect(screen.getByLabelText(`${g} reason`)).toBeInTheDocument();
    }
    expect(screen.getAllByLabelText(/ count$/)).toHaveLength(10);
    expect(screen.getByLabelText("Additional notes / evaluation reasoning")).toBeInTheDocument();
    expect(screen.getByText(/not parsed/i)).toBeInTheDocument();
    expect(document.querySelector('input[type="file"]')).toBeNull();
  });
});

describe("rating card: soft caps", () => {
  it("warns past 1,000 and 3,000 characters without blocking typing or submitting", async () => {
    await open(newSession());
    setValue("Change goal", "goal");
    setValue("Empathy reason", "x".repeat(1001));
    expect(screen.getByLabelText("Empathy reason")).toHaveValue("x".repeat(1001));
    expect(screen.getByText(/1,001 \/ 1,000/)).toHaveClass("counter-over");
    setValue("Additional notes / evaluation reasoning", "y".repeat(3001));
    expect(screen.getByText(/3,001 \/ 3,000/)).toHaveClass("counter-over");
    expect(screen.getByRole("button", { name: "Submit rating" })).toBeEnabled();
    expect(screen.getByRole("button", { name: /No rating/ })).toBeEnabled();
  });

  it("shows a quiet counter under the limit", async () => {
    await open(newSession());
    setValue("Empathy reason", "abc");
    expect(screen.getByText(/3 \/ 1,000/)).not.toHaveClass("counter-over");
  });
});

describe("rating card: autosave", () => {
  it("saves a draft on blur, shows 'Draft saved', and never satisfies the run gate", async () => {
    const sid = newSession();
    await open(sid);
    const user = userEvent.setup();
    await user.type(screen.getByLabelText("Change goal"), "Cut down");
    await user.tab();
    expect(await screen.findByText("Draft saved")).toBeInTheDocument();
    expect(puts).toHaveLength(1);
    expect(puts[0].body).toMatchObject({ final: false, card: { change_goal: "Cut down" } });
    const stored = mockBackend.getRating(UID, sid);
    expect(stored.draft?.card.change_goal).toBe("Cut down");
    expect(stored.final).toBeUndefined();
    expect(flags(sid).flags.rating_submitted).toBe(false);
  });

  it("flushes with keepalive when the page is hidden", async () => {
    const sid = newSession();
    await open(sid);
    setValue("Change goal", "On leave");
    window.dispatchEvent(new Event("pagehide"));
    await waitFor(() => expect(puts).toHaveLength(1));
    expect(puts[0].keepalive).toBe(true);
    expect(puts[0].body.final).toBe(false);
    await Promise.all(pending);
  });

  it("restores every field from the draft after a reload", async () => {
    const sid = newSession();
    await open(sid);
    setValue("Change goal", "Cut down");
    setValue(/coded from/i, "01:00");
    setValue(/coded to/i, "09:30");
    setValue("Partnership score", "4");
    setValue("Partnership reason", "collaborative");
    setValue("Question count", "7");
    setValue("Additional notes / evaluation reasoning", "free text");
    fireEvent.blur(screen.getByLabelText("Question count"));
    await screen.findByText("Draft saved");
    cleanup();

    await open(sid);
    await waitFor(() => expect(screen.getByLabelText("Change goal")).toHaveValue("Cut down"));
    expect(screen.getByLabelText(/coded from/i)).toHaveValue("01:00");
    expect(screen.getByLabelText(/coded to/i)).toHaveValue("09:30");
    expect(screen.getByLabelText("Partnership score")).toHaveValue("4");
    expect(screen.getByLabelText("Partnership reason")).toHaveValue("collaborative");
    expect(screen.getByLabelText("Question count")).toHaveValue(7);
    expect(screen.getByLabelText("Additional notes / evaluation reasoning")).toHaveValue("free text");
  });

  it("restores the last final card when there is no newer draft", async () => {
    const sid = newSession();
    mockBackend.putRating(UID, sid, { final: true, card: { change_goal: "Final goal", globals: { cct: { score: 2 } } } });
    await open(sid);
    await waitFor(() => expect(screen.getByLabelText("Change goal")).toHaveValue("Final goal"));
    expect(screen.getByLabelText("Cultivating Change Talk score")).toHaveValue("2");
  });
});

describe("rating card: submit", () => {
  it("'Submit rating' sends final:true with the card and sets the gate flags", async () => {
    const sid = newSession();
    await open(sid);
    setValue("Change goal", "Cut down");
    setValue("Empathy score", "5");
    await userEvent.click(screen.getByRole("button", { name: "Submit rating" }));
    expect(await screen.findByText(/Rating submitted/)).toBeInTheDocument();
    const last = puts.at(-1)!;
    expect(last.body.final).toBe(true);
    expect(last.body.no_rating).toBeUndefined();
    expect(last.body.card).toMatchObject({ change_goal: "Cut down", globals: { empathy: { score: 5 } } });
    expect(flags(sid).flags).toMatchObject({ rating_submitted: true, has_rating: true });
  });

  it("'No rating' sends final:true and no_rating:true with only goal and span", async () => {
    const sid = newSession();
    await open(sid);
    setValue("Change goal", "Cut down");
    setValue(/coded from/i, "00:10");
    setValue(/coded to/i, "00:50");
    setValue("Empathy score", "5");
    setValue("Additional notes / evaluation reasoning", "dropped");
    await userEvent.click(screen.getByRole("button", { name: /No rating/ }));
    expect(await screen.findByText(/without a rating/i)).toBeInTheDocument();
    const last = puts.at(-1)!;
    expect(last.body).toEqual({ final: true, no_rating: true, card: { change_goal: "Cut down", coded_span: { from_s: 10, to_s: 50 } } });
    expect(flags(sid).flags).toMatchObject({ rating_submitted: true, has_rating: false });
  });

  it("blocks locally without a change goal and sends nothing", async () => {
    await open(newSession());
    await userEvent.click(screen.getByRole("button", { name: "Submit rating" }));
    expect(await screen.findByText(/change goal is required/i)).toBeInTheDocument();
    expect(puts.filter((p) => p.body.final)).toEqual([]);
  });

  it("maps the API's 422 rating_invalid to per-field messages", async () => {
    const sid = newSession();
    await open(sid);
    setValue("Change goal", "g");
    setValue("Additional notes / evaluation reasoning", "y".repeat(3001));
    setValue("Giving Information note", "z".repeat(1001));
    await userEvent.click(screen.getByRole("button", { name: "Submit rating" }));
    const notes = screen.getByLabelText("Additional notes / evaluation reasoning");
    await waitFor(() => expect(notes).toHaveAccessibleDescription(/3,000/));
    expect(screen.getByLabelText("Giving Information note")).toHaveAccessibleDescription(/1,000/);
    expect(screen.getByRole("alert")).toHaveTextContent(/needs a change/i);
    expect(flags(sid).flags.rating_submitted).toBe(false);
  });
});
