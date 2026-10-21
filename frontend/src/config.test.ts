import { afterEach, describe, expect, it, vi } from "vitest";
import { getConfig } from "./config";

afterEach(() => vi.unstubAllEnvs());

describe("getConfig", () => {
  it.each([undefined, ""])("evalBase defaults to the local proxy for %j", (v) => {
    vi.stubEnv("VITE_EVAL_API_BASE", v);
    expect(getConfig().evalBase).toBe("/eval-api");
  });

  it("evalBase accepts a configured endpoint", () => {
    vi.stubEnv("VITE_EVAL_API_BASE", "http://localhost:9100");
    expect(getConfig().evalBase).toBe("http://localhost:9100");
  });

  it("mock is true only for exactly 'true'", () => {
    vi.stubEnv("VITE_MOCK", "true");
    expect(getConfig().mock).toBe(true);
  });

  it.each(["false", "", "TRUE", "1"])("mock is false for %j", (v) => {
    vi.stubEnv("VITE_MOCK", v);
    expect(getConfig().mock).toBe(false);
  });

  it("mock is false when unset", () => {
    vi.stubEnv("VITE_MOCK", undefined);
    expect(getConfig().mock).toBe(false);
  });

  it("auditUrl is passed through when set", () => {
    vi.stubEnv("VITE_AUDIT_URL", "http://localhost:8000/v1/audit");
    expect(getConfig().auditUrl).toBe("http://localhost:8000/v1/audit");
  });

  it.each([undefined, ""])("auditUrl is null for %j", (v) => {
    vi.stubEnv("VITE_AUDIT_URL", v);
    expect(getConfig().auditUrl).toBeNull();
  });
});
