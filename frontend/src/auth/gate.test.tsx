// @vitest-environment jsdom
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { getConfig } from "../config";
import { shouldGate } from "./gate";
import { Root } from "../Root";
import { createAuthSession } from "./session";
import { createFakeProvider } from "./fakeProvider";

afterEach(() => { cleanup(); vi.unstubAllEnvs(); });

describe("shouldGate", () => {
  const cfg = (env: Record<string, string>) => {
    for (const [k, v] of Object.entries(env)) vi.stubEnv(k, v);
    return getConfig();
  };
  it("is on only when VITE_AUTH_REQUIRED=true and not mock", () => {
    expect(shouldGate(cfg({ VITE_AUTH_REQUIRED: "true", VITE_MOCK: "false" }))).toBe(true);
  });
  it("is off by default (local dev)", () => {
    expect(shouldGate(cfg({ VITE_AUTH_REQUIRED: "", VITE_MOCK: "false" }))).toBe(false);
    expect(shouldGate(cfg({ VITE_AUTH_REQUIRED: "false", VITE_MOCK: "false" }))).toBe(false);
  });
  it("is off in mock mode even when required", () => {
    expect(shouldGate(cfg({ VITE_AUTH_REQUIRED: "true", VITE_MOCK: "true" }))).toBe(false);
  });
  it("authDomain defaults to admin.onolys.com and is overridable", () => {
    expect(cfg({ VITE_FIREBASE_AUTH_DOMAIN: "" }).firebase.authDomain).toBe("admin.onolys.com");
    expect(cfg({ VITE_FIREBASE_AUTH_DOMAIN: "x.example" }).firebase.authDomain).toBe("x.example");
  });
});

describe("Root", () => {
  it("without a session renders the app directly and never touches auth", () => {
    vi.stubEnv("VITE_MOCK", "true");
    render(<Root session={null} />);
    expect(screen.getByRole("navigation", { name: "Workspace" })).toBeTruthy();
  });
  it("with a signed-out session renders login instead of the app", async () => {
    vi.stubEnv("VITE_MOCK", "false");
    render(<Root session={createAuthSession(createFakeProvider())} />);
    expect(await screen.findByRole("button", { name: "Sign in" })).toBeTruthy();
    expect(screen.queryByRole("navigation", { name: "Workspace" })).toBeNull();
  });
});
