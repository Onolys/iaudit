// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { readFileSync, readdirSync } from "node:fs";
import { join } from "node:path";
import { afterEach, describe, expect, it, vi } from "vitest";
import { AuthGate } from "./AuthGate";
import { createAuthSession } from "./session";
import { createFakeProvider } from "./fakeProvider";

afterEach(cleanup);
const app = <div>the app</div>;

function mount(user: { email: string } | null = null) {
  const provider = createFakeProvider(user);
  const session = createAuthSession(provider);
  render(<AuthGate session={session}>{app}</AuthGate>);
  return { provider, session };
}

describe("AuthGate", () => {
  it("signed out: shows login, not the app", async () => {
    mount();
    expect(await screen.findByRole("button", { name: "Sign in" })).toBeTruthy();
    expect(screen.queryByText("the app")).toBeNull();
  });

  it("email/password sign-in then shows the app", async () => {
    const { provider } = mount();
    fireEvent.change(await screen.findByLabelText("Email"), { target: { value: "a@b.co" } });
    fireEvent.change(screen.getByLabelText("Password"), { target: { value: "pw" } });
    fireEvent.click(screen.getByRole("button", { name: "Sign in" }));
    expect(await screen.findByText("the app")).toBeTruthy();
    expect(provider.signInWithEmail).toHaveBeenCalledWith("a@b.co", "pw");
  });

  it("Google sign-in then shows the app", async () => {
    const { provider } = mount();
    fireEvent.click(await screen.findByRole("button", { name: "Sign in with Google" }));
    expect(await screen.findByText("the app")).toBeTruthy();
    expect(provider.signInWithGoogle).toHaveBeenCalledOnce();
  });

  it("shows a sign-in error and stays on login", async () => {
    const provider = createFakeProvider();
    provider.signInWithEmail.mockRejectedValueOnce(new Error("bad"));
    render(<AuthGate session={createAuthSession(provider)}>{app}</AuthGate>);
    fireEvent.change(await screen.findByLabelText("Email"), { target: { value: "a@b.co" } });
    fireEvent.change(screen.getByLabelText("Password"), { target: { value: "x" } });
    fireEvent.click(screen.getByRole("button", { name: "Sign in" }));
    expect((await screen.findByRole("alert")).textContent).toContain("Sign-in failed");
    expect(screen.queryByText("the app")).toBeNull();
  });

  it("signed in: shows the app with a Sign out button that returns to login", async () => {
    const { provider } = mount({ email: "a@b.co" });
    expect(await screen.findByText("the app")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Sign out" }));
    expect(await screen.findByRole("button", { name: "Sign in" })).toBeTruthy();
    expect(provider.signOut).toHaveBeenCalledOnce();
  });

  it("401 then one refresh, a second 401 goes to login", async () => {
    const { provider, session } = mount({ email: "a@b.co" });
    await screen.findByText("the app");
    const base = vi.fn(async () => new Response("{}", { status: 401 }));
    const r = await session.createFetch(base as unknown as typeof fetch)("https://x", {});
    expect(r.status).toBe(401);
    expect(base).toHaveBeenCalledTimes(2);
    expect(provider.getIdToken).toHaveBeenLastCalledWith(true);
    expect(await screen.findByRole("button", { name: "Sign in" })).toBeTruthy();
  });

  it("403 shows the not-on-admin-list screen with sign out", async () => {
    const { session } = mount({ email: "a@b.co" });
    await screen.findByText("the app");
    const base = vi.fn(async () => new Response("{}", { status: 403 }));
    await session.createFetch(base as unknown as typeof fetch)("https://x", {});
    expect(await screen.findByText(/not on the admin list/i)).toBeTruthy();
    expect(screen.queryByText("the app")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Sign out" }));
    await waitFor(() => expect(screen.getByRole("button", { name: "Sign in" })).toBeTruthy());
  });

  it("has no sign-up or MFA UI", async () => {
    mount();
    await screen.findByRole("button", { name: "Sign in" });
    const text = document.body.textContent ?? "";
    expect(text).not.toMatch(/sign.?up|create (an )?account|register|forgot|verification code|two-factor|mfa|authenticator/i);
    expect(document.querySelectorAll("a")).toHaveLength(0);
  });

  it("auth source never imports sign-up or MFA APIs", () => {
    const dir = join(process.cwd(), "src/auth");
    const src = readdirSync(dir).filter(f => /\.tsx?$/.test(f) && !f.includes(".test.") && f !== "fakeProvider.ts");
    const all = src.map(f => readFileSync(join(dir, f), "utf8")).join("\n");
    expect(all).not.toMatch(/createUserWithEmailAndPassword|multiFactor|MultiFactor|sendEmailVerification/);
    expect(all).not.toMatch(/from "firebase\/(?!app"|auth")/);
  });
});
