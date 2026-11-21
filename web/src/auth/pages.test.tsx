import { act, cleanup, fireEvent, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { here, renderApp } from "../test/renderApp";
import { createFakeAuthService } from "./fakeService";

const h1 = (name: string) => screen.findByRole("heading", { level: 1, name });

describe("sign up", () => {
  it("creates an account, sends verification and lands on /verify-email keeping ?next=", async () => {
    const user = userEvent.setup();
    const { router, service } = renderApp("/signup?next=%2Fsettings");
    await h1("Sign up");
    await user.type(screen.getByLabelText("Email"), "new@clinic.org");
    await user.type(screen.getByLabelText("Password"), "longenough1");
    await user.click(screen.getByRole("button", { name: "Create account" }));
    await h1("Verify your email");
    expect(service.calls.verificationEmails).toBe(1);
    expect(here(router)).toBe("/verify-email?next=%2Fsettings");
  });

  it("blocks passwords under 8 characters with an error summary and does not call the service", async () => {
    const user = userEvent.setup();
    const { service } = renderApp("/signup");
    await h1("Sign up");
    await user.type(screen.getByLabelText("Email"), "new@clinic.org");
    await user.type(screen.getByLabelText("Password"), "short");
    await user.click(screen.getByRole("button", { name: "Create account" }));
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("at least 8 characters");
    expect(alert).toHaveFocus();
    expect(service.calls.signUps).toBe(0);
  });

  it("offers login when the email is already in use", async () => {
    const user = userEvent.setup();
    const service = createFakeAuthService();
    await service.signUp("dup@clinic.org", "longenough1");
    await service.signOut();
    renderApp("/signup?next=%2Fsettings", { service });
    await h1("Sign up");
    await user.type(screen.getByLabelText("Email"), "dup@clinic.org");
    await user.type(screen.getByLabelText("Password"), "longenough1");
    await user.click(screen.getByRole("button", { name: "Create account" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("already exists");
    const link = screen.getByRole("link", { name: "Log in instead" });
    expect(link).toHaveAttribute("href", "/login?next=%2Fsettings");
  });

  it("continues with Google", async () => {
    const user = userEvent.setup();
    const { service } = renderApp("/signup");
    await h1("Sign up");
    await user.click(screen.getByRole("button", { name: "Continue with Google" }));
    await waitFor(() => expect(service.calls.googleSignIns).toBe(1));
    await h1("Sessions"); // Google accounts arrive verified
  });
});

describe("log in", () => {
  it("signs in and goes to ?next=", async () => {
    const user = userEvent.setup();
    const service = createFakeAuthService();
    await service.signUp("a@clinic.org", "longenough1");
    service.markVerified("a@clinic.org");
    await service.signOut();
    const { router } = renderApp("/login?next=%2Fsettings", { service });
    await h1("Log in");
    await user.type(screen.getByLabelText("Email"), "a@clinic.org");
    await user.type(screen.getByLabelText("Password"), "longenough1");
    await user.click(screen.getByRole("button", { name: "Log in" }));
    await h1("Settings");
    expect(here(router)).toBe("/settings");
  });

  it("shows a plain-text error for a wrong password", async () => {
    const user = userEvent.setup();
    const service = createFakeAuthService();
    await service.signUp("a@clinic.org", "longenough1");
    await service.signOut();
    renderApp("/login", { service });
    await h1("Log in");
    await user.type(screen.getByLabelText("Email"), "a@clinic.org");
    await user.type(screen.getByLabelText("Password"), "wrongwrong");
    await user.click(screen.getByRole("button", { name: "Log in" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("That email and password don't match");
  });

  it("links to sign up and forgot password, carrying ?next=", async () => {
    renderApp("/login?next=%2Fsettings");
    await h1("Log in");
    expect(screen.getByRole("link", { name: "Create an account" })).toHaveAttribute("href", "/signup?next=%2Fsettings");
    expect(screen.getByRole("link", { name: "Forgot your password?" })).toHaveAttribute("href", "/forgot-password?next=%2Fsettings");
  });

  it("ignores an unsafe ?next= after sign-in", async () => {
    const { router } = renderApp("/login?next=%2F%2Fevil.com", { user: { email: "a@clinic.org", verified: true } });
    await h1("Sessions");
    expect(here(router)).toBe("/");
  });
});

describe("forgot password", () => {
  const CONFIRM = "If an account exists for that email, we've sent a link to reset your password.";

  it("shows the same confirmation for a known and an unknown email", async () => {
    const service = createFakeAuthService();
    await service.signUp("known@clinic.org", "longenough1");
    await service.signOut();
    const texts: string[] = [];
    for (const email of ["known@clinic.org", "nobody@clinic.org"]) {
      const user = userEvent.setup();
      renderApp("/forgot-password", { service });
      await h1("Reset your password");
      await user.type(screen.getByLabelText("Email"), email);
      await user.click(screen.getByRole("button", { name: "Send reset link" }));
      texts.push((await screen.findByRole("status")).textContent ?? "");
      cleanup();
    }
    expect(texts[0]).toBe(CONFIRM);
    expect(texts[1]).toBe(CONFIRM);
    expect(service.calls.resets).toEqual(["known@clinic.org", "nobody@clinic.org"]);
  });
});

describe("verify email", () => {
  afterEach(() => vi.useRealTimers());

  it("mentions the spam folder", async () => {
    renderApp("/verify-email", { user: { email: "a@clinic.org", verified: false } });
    await h1("Verify your email");
    expect(screen.getByText(/spam folder/i)).toBeInTheDocument();
    expect(screen.getByText(/a@clinic\.org/)).toBeInTheDocument();
  });

  it("Resend sends mail then locks for 60 seconds with a countdown", async () => {
    const { service } = renderApp("/verify-email", { user: { email: "a@clinic.org", verified: false } });
    await h1("Verify your email");
    vi.useFakeTimers();
    // RTL's async wrapper deadlocks on vitest fake timers, so drive the click synchronously.
    await act(async () => fireEvent.click(screen.getByRole("button", { name: "Resend email" })));
    expect(service.calls.verificationEmails).toBe(1);
    const locked = screen.getByRole("button", { name: /Resend in 60s/ });
    expect(locked).toBeDisabled();
    for (let i = 0; i < 30; i++) await act(async () => void vi.advanceTimersByTime(1000));
    expect(screen.getByRole("button", { name: /Resend in 30s/ })).toBeDisabled();
    for (let i = 0; i < 30; i++) await act(async () => void vi.advanceTimersByTime(1000));
    const again = screen.getByRole("button", { name: "Resend email" });
    expect(again).toBeEnabled();
    expect(service.calls.verificationEmails).toBe(1);
  });

  it("\"I've verified\" force-refreshes the token and continues to ?next=", async () => {
    const user = userEvent.setup();
    const { service, router } = renderApp("/verify-email?next=%2Fsettings", { user: { email: "a@clinic.org", verified: false } });
    await h1("Verify your email");
    service.markVerified("a@clinic.org");
    await user.click(screen.getByRole("button", { name: "I've verified" }));
    await h1("Settings");
    expect(service.calls.forcedRefreshes).toBe(1);
    expect(here(router)).toBe("/settings");
  });

  it("\"I've verified\" while still unverified explains and stays", async () => {
    const user = userEvent.setup();
    const { service } = renderApp("/verify-email", { user: { email: "a@clinic.org", verified: false } });
    await h1("Verify your email");
    await user.click(screen.getByRole("button", { name: "I've verified" }));
    expect(await screen.findByRole("status")).toHaveTextContent("haven't seen your verification");
    expect(service.calls.forcedRefreshes).toBe(1);
  });

  it("auto-checks (with a forced refresh) when the tab regains focus", async () => {
    // The heading shows on DOM commit, before the passive effect adds the window focus listener;
    // a focus event fired earlier is lost. Wait for the listener itself, not the heading.
    const add = vi.spyOn(window, "addEventListener");
    const { service } = renderApp("/verify-email", { user: { email: "a@clinic.org", verified: false } });
    await h1("Verify your email");
    await waitFor(() => expect(add).toHaveBeenCalledWith("focus", expect.any(Function)));
    add.mockRestore();
    service.markVerified("a@clinic.org");
    act(() => void window.dispatchEvent(new Event("focus")));
    await h1("Sessions");
    expect(service.calls.forcedRefreshes).toBe(1);
  });
});
