import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { renderApp } from "../test/renderApp";

const VERIFIED = { email: "a@clinic.org", verified: true };

const table: Array<[string, string]> = [
  ["/sample-report", "Sample report"],
  ["/", "Sessions"],
  ["/sessions/new", "New session"],
  ["/sessions/abc123", "Session"],
  ["/sessions/abc123/reports/2", "Report"],
  ["/settings", "Settings"],
];

const authPages: Array<[string, string]> = [
  ["/signup", "Sign up"],
  ["/login", "Log in"],
  ["/forgot-password", "Reset your password"],
];

describe("route table", () => {
  it.each(table)("%s renders its placeholder h1 for a verified user", async (path, heading) => {
    renderApp(path, { user: VERIFIED });
    expect(await screen.findByRole("heading", { level: 1, name: heading })).toBeInTheDocument();
  });

  it.each(authPages)("%s renders its h1 when signed out", async (path, heading) => {
    renderApp(path);
    expect(await screen.findByRole("heading", { level: 1, name: heading })).toBeInTheDocument();
  });

  it("/verify-email renders for a signed-in unverified user", async () => {
    renderApp("/verify-email", { user: { email: "a@clinic.org", verified: false } });
    expect(await screen.findByRole("heading", { level: 1, name: "Verify your email" })).toBeInTheDocument();
  });

  it("has banner, nav, main and contentinfo landmarks", async () => {
    renderApp("/", { user: VERIFIED });
    await screen.findByRole("heading", { level: 1, name: "Sessions" });
    expect(screen.getByRole("banner")).toBeInTheDocument();
    expect(screen.getByRole("navigation")).toBeInTheDocument();
    expect(screen.getByRole("main")).toBeInTheDocument();
    expect(screen.getByRole("contentinfo")).toBeInTheDocument();
  });

  it("shows a not-found page for unknown paths", async () => {
    renderApp("/nope/nothing");
    expect(await screen.findByRole("heading", { level: 1, name: "Page not found" })).toBeInTheDocument();
  });

  it("moves focus to the h1 on navigation", async () => {
    const { router } = renderApp("/login");
    expect(await screen.findByRole("heading", { level: 1, name: "Log in" })).toHaveFocus();
    await userEvent.click(screen.getByRole("link", { name: "Sample report" }));
    expect(router.state.location.pathname).toBe("/sample-report");
    expect(await screen.findByRole("heading", { level: 1, name: "Sample report" })).toHaveFocus();
  });
});
