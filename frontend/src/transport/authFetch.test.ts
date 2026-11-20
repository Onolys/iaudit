import { describe, expect, it, vi } from "vitest";
import { createAuthFetch } from "./authFetch";

const res = (status: number) => new Response("{}", { status });
function setup(statuses: number[]) {
  const base = vi.fn(async (_u: RequestInfo | URL, _i?: RequestInit) => res(statuses.shift() ?? 200));
  const getToken = vi.fn(async (force?: boolean) => (force ? "fresh" : "old"));
  const onUnauthorized = vi.fn();
  const onForbidden = vi.fn();
  const f = createAuthFetch({ fetch: base as unknown as typeof fetch, getToken, onUnauthorized, onForbidden });
  const auth = (i: number) => new Headers(base.mock.calls[i]![1]!.headers).get("Authorization");
  return { f, base, getToken, onUnauthorized, onForbidden, auth };
}

describe("createAuthFetch", () => {
  it("attaches the bearer token and keeps other headers", async () => {
    const s = setup([200]);
    const r = await s.f("https://x/v1/audit", { method: "POST", headers: { "Content-Type": "application/json" }, body: "{}" });
    expect(r.status).toBe(200);
    expect(s.auth(0)).toBe("Bearer old");
    expect(new Headers(s.base.mock.calls[0]![1]!.headers).get("Content-Type")).toBe("application/json");
    expect(s.getToken).toHaveBeenCalledWith(false);
  });

  it("sends no Authorization header when there is no token", async () => {
    const s = setup([200]);
    s.getToken.mockResolvedValueOnce(null as never);
    await s.f("https://x", {});
    expect(s.auth(0)).toBeNull();
  });

  it("401 forces exactly one refresh, retries with the fresh token, and succeeds", async () => {
    const s = setup([401, 200]);
    const r = await s.f("https://x", { method: "POST", body: "{}" });
    expect(r.status).toBe(200);
    expect(s.base).toHaveBeenCalledTimes(2);
    expect(s.getToken).toHaveBeenNthCalledWith(2, true);
    expect(s.auth(1)).toBe("Bearer fresh");
    expect(s.onUnauthorized).not.toHaveBeenCalled();
  });

  it("a second 401 does not refresh again and sends the user to login", async () => {
    const s = setup([401, 401]);
    const r = await s.f("https://x", {});
    expect(r.status).toBe(401);
    expect(s.base).toHaveBeenCalledTimes(2);
    expect(s.getToken).toHaveBeenCalledTimes(2);
    expect(s.onUnauthorized).toHaveBeenCalledOnce();
  });

  it("403 is reported once, not retried", async () => {
    const s = setup([403]);
    const r = await s.f("https://x", {});
    expect(r.status).toBe(403);
    expect(s.base).toHaveBeenCalledTimes(1);
    expect(s.onForbidden).toHaveBeenCalledOnce();
    expect(s.onUnauthorized).not.toHaveBeenCalled();
  });
});
