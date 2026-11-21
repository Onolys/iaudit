import { describe, expect, it } from "vitest";
import { MIN_PASSWORD_LENGTH, mapAuthError } from "./errors";

describe("mapAuthError", () => {
  it("maps wrong credentials to one plain message", () => {
    for (const code of ["auth/wrong-password", "auth/invalid-credential", "auth/user-not-found"]) {
      expect(mapAuthError(code).message).toBe("That email and password don't match. Try again or reset your password.");
    }
  });
  it("states the 8 character minimum for weak passwords", () => {
    expect(MIN_PASSWORD_LENGTH).toBe(8);
    expect(mapAuthError("auth/weak-password").message).toMatch(/at least 8 characters/);
  });
  it("offers login when the email is already in use", () => {
    const m = mapAuthError("auth/email-already-in-use");
    expect(m.offerLogin).toBe(true);
    expect(m.message).toMatch(/already exists/);
  });
  it("covers network, throttling, invalid email, cancelled popup and unknown codes", () => {
    expect(mapAuthError("auth/network-request-failed").message).toMatch(/connection/i);
    expect(mapAuthError("auth/too-many-requests").message).toMatch(/too many/i);
    expect(mapAuthError("auth/invalid-email").message).toMatch(/valid email/i);
    expect(mapAuthError("auth/popup-closed-by-user").message).toMatch(/cancelled/i);
    expect(mapAuthError("auth/whatever").message).toBe("Something went wrong. Please try again.");
    expect(mapAuthError(undefined).offerLogin).toBeFalsy();
  });
});
