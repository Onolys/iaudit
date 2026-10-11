import { afterEach, describe, expect, it, vi } from "vitest";
import { getConfig } from "./config";

afterEach(() => vi.unstubAllEnvs());

describe("getConfig", () => {
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
    vi.stubEnv("VITE_AUDIT_URL", "http://localhost:8000/audit");
    expect(getConfig().auditUrl).toBe("http://localhost:8000/audit");
  });

  it.each([undefined, ""])("auditUrl is null for %j", (v) => {
    vi.stubEnv("VITE_AUDIT_URL", v);
    expect(getConfig().auditUrl).toBeNull();
  });
});
