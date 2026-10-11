import { readFileSync } from "node:fs";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { AuditRequest } from "../contract";
import { TIMEOUT_MS, postAudit } from "./client";
import { isRetryable } from "./errors";
import type { LoadError } from "./errors";

const example = (name: string) =>
  readFileSync(new URL(`../../../docs/contracts/examples/${name}.json`, import.meta.url), "utf8");

const request = JSON.parse(example("request")) as AuditRequest;
const URL_ = "https://audit.example/api";

type FetchFn = typeof fetch;

/** fetch that never answers until its signal aborts. */
function hangingFetch(): FetchFn {
  return ((_url: unknown, init?: RequestInit) =>
    new Promise((_resolve, reject) => {
      init?.signal?.addEventListener("abort", () => reject(new DOMException("aborted", "AbortError")));
    })) as FetchFn;
}

const reply = (status: number, body: string) => vi.fn(async () => new Response(body, { status })) as unknown as FetchFn & ReturnType<typeof vi.fn>;

async function errorOf(p: ReturnType<typeof postAudit>): Promise<LoadError> {
  const r = await p;
  if (r.ok) throw new Error("expected error");
  return r.error;
}

beforeEach(() => vi.useFakeTimers());
afterEach(() => vi.useRealTimers());

describe("request shape", () => {
  it("POSTs JSON without credentials and returns the body text", async () => {
    const f = reply(200, '{"a":1}');
    const r = await postAudit(URL_, request, { fetch: f, signal: new AbortController().signal });
    expect(r).toEqual({ ok: true, value: '{"a":1}' });
    const [url, init] = (f as unknown as ReturnType<typeof vi.fn>).mock.calls[0] as [string, RequestInit];
    expect(url).toBe(URL_);
    expect(init.method).toBe("POST");
    expect(init.credentials).toBe("omit");
    expect(init.headers).toEqual({ "Content-Type": "application/json", Accept: "application/json" });
    expect(JSON.parse(init.body as string)).toEqual(request);
  });
});

describe("failures", () => {
  it("maps a rejected fetch to network with the url", async () => {
    const f = vi.fn(async () => { throw new TypeError("Failed to fetch"); }) as unknown as FetchFn;
    expect(await errorOf(postAudit(URL_, request, { fetch: f, signal: new AbortController().signal }))).toEqual({ kind: "network", url: URL_ });
  });

  it("times out at exactly 120 s and aborts the fetch signal", async () => {
    expect(TIMEOUT_MS).toBe(120_000);
    let seen: AbortSignal | undefined;
    const inner = hangingFetch();
    const f = ((u: string, init: RequestInit) => { seen = init.signal as AbortSignal; return inner(u, init); }) as FetchFn;
    const p = errorOf(postAudit(URL_, request, { fetch: f, signal: new AbortController().signal }));
    await vi.advanceTimersByTimeAsync(119_999);
    expect(seen?.aborted).toBe(false);
    await vi.advanceTimersByTimeAsync(1);
    expect(seen?.aborted).toBe(true);
    expect(await p).toEqual({ kind: "timeout", seconds: 120 });
  });

  it("times out during a slow body read", async () => {
    const f = (async (_u: string, init: RequestInit) => ({
      ok: true,
      status: 200,
      text: () => new Promise((_r, rej) => init.signal?.addEventListener("abort", () => rej(new DOMException("a", "AbortError")))),
    })) as unknown as FetchFn;
    const p = errorOf(postAudit(URL_, request, { fetch: f, signal: new AbortController().signal }));
    await vi.advanceTimersByTimeAsync(120_000);
    expect(await p).toEqual({ kind: "timeout", seconds: 120 });
  });

  it("cancel aborts the fetch signal and yields cancelled", async () => {
    const ctl = new AbortController();
    let seen: AbortSignal | undefined;
    const inner = hangingFetch();
    const f = ((u: string, init: RequestInit) => { seen = init.signal as AbortSignal; return inner(u, init); }) as FetchFn;
    const p = errorOf(postAudit(URL_, request, { fetch: f, signal: ctl.signal }));
    ctl.abort();
    expect(await p).toEqual({ kind: "cancelled" });
    expect(seen?.aborted).toBe(true);
  });

  it("an already-aborted signal never calls fetch", async () => {
    const ctl = new AbortController();
    ctl.abort();
    const f = reply(200, "{}");
    expect(await errorOf(postAudit(URL_, request, { fetch: f, signal: ctl.signal }))).toEqual({ kind: "cancelled" });
    expect(f).not.toHaveBeenCalled();
  });

  it("clears the timer after success", async () => {
    await postAudit(URL_, request, { fetch: reply(200, "{}"), signal: new AbortController().signal });
    expect(vi.getTimerCount()).toBe(0);
  });
});

describe("non-2xx", () => {
  const run = (status: number, body: string) =>
    errorOf(postAudit(URL_, request, { fetch: reply(status, body), signal: new AbortController().signal }));

  it("400 with a valid error body shows its message", async () => {
    expect(await run(400, example("error"))).toEqual({
      kind: "http_4xx",
      status: 400,
      message: "transcript must contain at least one turn.",
    });
  });

  it("500 with an HTML body shows no body text", async () => {
    expect(await run(500, "<html>boom</html>")).toEqual({ kind: "http_5xx", status: 500, message: undefined });
  });

  it.each(["", "{}", "[]", "null", '{"error":{"message":"x"}}'])("ignores invalid error body %j", async (body) => {
    const e = await run(422, body);
    expect(e).toMatchObject({ kind: "http_4xx", status: 422 });
    expect((e as { message?: string }).message).toBeUndefined();
  });

  it("treats a 302 like 5xx", async () => {
    expect(await run(302, "")).toMatchObject({ kind: "http_5xx", status: 302 });
  });
});

describe("isRetryable", () => {
  const cases: [LoadError, boolean][] = [
    [{ kind: "network", url: "u" }, true],
    [{ kind: "timeout", seconds: 120 }, true],
    [{ kind: "cancelled" }, true],
    [{ kind: "http_5xx", status: 503 }, true],
    [{ kind: "http_4xx", status: 408 }, true],
    [{ kind: "http_4xx", status: 429 }, true],
    [{ kind: "http_4xx", status: 400 }, false],
    [{ kind: "config_missing" }, false],
    [{ kind: "mock_no_match" }, false],
    [{ kind: "invalid_request_file", reason: "empty" }, false],
    [{ kind: "invalid_response", reason: "empty" }, false],
    [{ kind: "request_id_mismatch", expected: "a", received: "b" }, false],
  ];
  it.each(cases)("%j -> %s", (e, want) => expect(isRetryable(e)).toBe(want));
});
