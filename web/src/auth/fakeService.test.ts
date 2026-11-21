import { describe, expect, it } from "vitest";
import { createFakeAuthService } from "./fakeService";

describe("fake auth service", () => {
  it("signs up unverified, sends a verification email, and issues SP04 fake tokens", async () => {
    const s = createFakeAuthService();
    await s.signUp("a@b.co", "password1");
    expect(s.calls.verificationEmails).toBe(1);
    expect(await s.getToken()).toMatch(/^test:u_/);
    let seen: unknown = "none";
    s.onAuthStateChanged((u) => (seen = u));
    await Promise.resolve();
    expect(seen).toMatchObject({ email: "a@b.co", emailVerified: false });
  });
  it("rejects duplicates and bad passwords with firebase-style codes", async () => {
    const s = createFakeAuthService();
    await s.signUp("a@b.co", "password1");
    await expect(s.signUp("a@b.co", "password1")).rejects.toMatchObject({ code: "auth/email-already-in-use" });
    await expect(s.signIn("a@b.co", "nope")).rejects.toMatchObject({ code: "auth/invalid-credential" });
  });
  it("refreshUser counts a forced token refresh and picks up server-side verification", async () => {
    const s = createFakeAuthService();
    await s.signUp("a@b.co", "password1");
    s.markVerified("a@b.co");
    const u = await s.refreshUser();
    expect(u?.emailVerified).toBe(true);
    expect(s.calls.forcedRefreshes).toBe(1);
  });
  it("signOut clears the user and the token", async () => {
    const s = createFakeAuthService();
    s.signedInAs("a@b.co", { verified: true });
    await s.signOut();
    expect(await s.getToken()).toBeNull();
  });
});
