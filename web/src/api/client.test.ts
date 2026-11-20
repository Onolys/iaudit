import { http, HttpResponse } from "msw";
import { describe, expect, it, vi } from "vitest";
import { server } from "../mocks/server";
import { createApiClient, unwrap } from "./client";
import { ApiError } from "./errors";

const BASE = "http://localhost/v1";

const errBody = (status: number, code: string) => ({
  schema_version: "0.0.1",
  status,
  message: "fixed text",
  details: [{ code, message: "fixed text" }],
  request_id: "req_9",
});

function setup(
  getToken = vi.fn(async (force?: boolean): Promise<string | null> => (force ? "fresh" : "stale")),
) {
  const onSessionExpired = vi.fn();
  const client = createApiClient({ baseUrl: BASE, getToken, onSessionExpired });
  return { client, getToken, onSessionExpired };
}

describe("bearer auth", () => {
  it("sends the token from the provider as a Bearer header", async () => {
    let auth: string | null = null;
    server.use(
      http.get(`${BASE}/usage`, ({ request }) => {
        auth = request.headers.get("authorization");
        return HttpResponse.json({ runs_today: 1, daily_cap: 20, resets_at: "x" });
      }),
    );
    const { client, getToken } = setup();
    const res = await client.GET("/usage");
    expect(res.data?.daily_cap).toBe(20);
    expect(auth).toBe("Bearer stale");
    expect(getToken).toHaveBeenCalledWith(false);
  });

  it("sends no Authorization header when there is no token", async () => {
    let auth: string | null = "unset";
    server.use(
      http.get(`${BASE}/usage`, ({ request }) => {
        auth = request.headers.get("authorization");
        return HttpResponse.json({ runs_today: 0, daily_cap: 20, resets_at: "x" });
      }),
    );
    const { client } = setup(vi.fn(async (): Promise<string | null> => null));
    await client.GET("/usage");
    expect(auth).toBeNull();
  });
});

describe("401 handling", () => {
  it("force-refreshes the token once and retries the request", async () => {
    const seen: (string | null)[] = [];
    server.use(
      http.get(`${BASE}/usage`, ({ request }) => {
        const a = request.headers.get("authorization");
        seen.push(a);
        if (a === "Bearer stale") return HttpResponse.json(errBody(401, "unauthenticated"), { status: 401 });
        return HttpResponse.json({ runs_today: 2, daily_cap: 20, resets_at: "x" });
      }),
    );
    const { client, getToken, onSessionExpired } = setup();
    const res = await client.GET("/usage");
    expect(res.data?.runs_today).toBe(2);
    expect(seen).toEqual(["Bearer stale", "Bearer fresh"]);
    expect(getToken.mock.calls).toEqual([[false], [true]]);
    expect(onSessionExpired).not.toHaveBeenCalled();
  });

  it("replays a request body on the retry", async () => {
    const bodies: unknown[] = [];
    server.use(
      http.post(`${BASE}/sessions/s1/runs`, async ({ request }) => {
        bodies.push(await request.json());
        if (request.headers.get("authorization") === "Bearer stale")
          return HttpResponse.json(errBody(401, "unauthenticated"), { status: 401 });
        return HttpResponse.json({ run_id: "r1" }, { status: 202 });
      }),
    );
    const { client } = setup();
    const res = await client.POST("/sessions/{id}/runs", {
      params: { path: { id: "s1" } },
      body: { n_runs: 1 },
    });
    expect(res.data?.run_id).toBe("r1");
    expect(bodies).toEqual([{ n_runs: 1 }, { n_runs: 1 }]);
  });

  it("signs out (once) after a second 401 and never retries a third time", async () => {
    let calls = 0;
    server.use(
      http.get(`${BASE}/usage`, () => {
        calls += 1;
        return HttpResponse.json(errBody(401, "unauthenticated"), { status: 401 });
      }),
    );
    const { client, getToken, onSessionExpired } = setup();
    const res = await client.GET("/usage");
    expect(calls).toBe(2);
    expect(getToken.mock.calls).toEqual([[false], [true]]);
    expect(onSessionExpired).toHaveBeenCalledTimes(1);
    expect(res.response.status).toBe(401);
    expect(() => unwrap(res)).toThrow(ApiError);
  });

  it("does not refresh or sign out on other statuses", async () => {
    server.use(
      http.get(`${BASE}/usage`, () =>
        HttpResponse.json(errBody(403, "forbidden"), { status: 403 }),
      ),
    );
    const { client, getToken, onSessionExpired } = setup();
    await client.GET("/usage");
    expect(getToken).toHaveBeenCalledTimes(1);
    expect(onSessionExpired).not.toHaveBeenCalled();
  });
});

describe("Idempotency-Key", () => {
  type Seen = { method: string; path: string; key: string | null };
  function capture(): Seen[] {
    const seen: Seen[] = [];
    server.use(
      http.all(`${BASE}/*`, ({ request }) => {
        seen.push({
          method: request.method,
          path: new URL(request.url).pathname,
          key: request.headers.get("idempotency-key"),
        });
        return HttpResponse.json({ session: { id: "s1", status: "created" } }, { status: 201 });
      }),
    );
    return seen;
  }

  it("is sent on POST /sessions with the caller's key", async () => {
    const seen = capture();
    const { client } = setup();
    await client.POST("/sessions", {
      params: { header: { "Idempotency-Key": "form-key-1" } },
      body: { language: "auto" },
    });
    expect(seen).toEqual([{ method: "POST", path: "/v1/sessions", key: "form-key-1" }]);
  });

  it("is generated for POST /sessions when the caller gives none", async () => {
    const seen = capture();
    const { client } = setup();
    await client.POST("/sessions", { body: {} });
    expect(seen[0].key).toMatch(/^[0-9a-f-]{36}$/);
  });

  it("is never sent on any other request, even if a caller passes one", async () => {
    const seen = capture();
    const { client } = setup();
    await client.POST("/sessions/{id}/runs", {
      params: { path: { id: "s1" }, header: { "Idempotency-Key": "nope" } } as never,
      body: {},
    });
    await client.POST("/sessions/{id}/audio", {
      params: { path: { id: "s1" } },
      body: { content_type: "audio/mpeg", size_bytes: 1, filename_ext: "mp3" },
    });
    await client.PUT("/sessions/{id}/rating", {
      params: { path: { id: "s1" } },
      body: { final: false, card: {} },
    });
    await client.GET("/sessions");
    await client.DELETE("/sessions/{id}", { params: { path: { id: "s1" } } });
    expect(seen.map((s) => s.key)).toEqual([null, null, null, null, null]);
    expect(seen).toHaveLength(5);
  });

  it("keeps the same key on the 401 retry", async () => {
    const keys: (string | null)[] = [];
    server.use(
      http.post(`${BASE}/sessions`, ({ request }) => {
        keys.push(request.headers.get("idempotency-key"));
        if (request.headers.get("authorization") === "Bearer stale")
          return HttpResponse.json(errBody(401, "unauthenticated"), { status: 401 });
        return HttpResponse.json({ session: { id: "s1", status: "created" } }, { status: 201 });
      }),
    );
    const { client } = setup();
    await client.POST("/sessions", { body: {} });
    expect(keys).toHaveLength(2);
    expect(keys[0]).toBe(keys[1]);
  });
});

describe("unwrap", () => {
  it("returns data on success", async () => {
    server.use(
      http.get(`${BASE}/usage`, () =>
        HttpResponse.json({ runs_today: 3, daily_cap: 20, resets_at: "x" }),
      ),
    );
    const { client } = setup();
    expect(unwrap(await client.GET("/usage")).runs_today).toBe(3);
  });

  it("returns undefined for a 204", async () => {
    server.use(http.delete(`${BASE}/sessions/s1`, () => new HttpResponse(null, { status: 204 })));
    const { client } = setup();
    expect(unwrap(await client.DELETE("/sessions/{id}", { params: { path: { id: "s1" } } }))).toBeUndefined();
  });

  it("throws an ApiError carrying code, status and request id", async () => {
    server.use(
      http.post(`${BASE}/sessions/s1/runs`, () =>
        HttpResponse.json(errBody(429, "daily_cap_reached"), { status: 429 }),
      ),
    );
    const { client } = setup();
    const res = await client.POST("/sessions/{id}/runs", { params: { path: { id: "s1" } } });
    try {
      unwrap(res);
      expect.unreachable();
    } catch (e) {
      expect(e).toBeInstanceOf(ApiError);
      expect((e as ApiError).code).toBe("daily_cap_reached");
      expect((e as ApiError).status).toBe(429);
      expect((e as ApiError).requestId).toBe("req_9");
    }
  });
});
