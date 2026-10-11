import { describe, expect, it, vi, afterEach, beforeEach } from "vitest";
import { buildRegistry, defaultRegistry, lookupMock, parseFixtureName } from "./registry";

describe("parseFixtureName", () => {
  it.each([
    ["../x/examples/request.json", { name: "default", kind: "request" }],
    ["../x/examples/response.json", { name: "default", kind: "response" }],
    ["../x/examples/partial.request.json", { name: "partial", kind: "request" }],
    ["../x/examples/a.b.response.json", { name: "a.b", kind: "response" }],
    ["../x/examples/error.json", null],
    ["../x/examples/notes.txt", null],
  ])("%s", (path, want) => expect(parseFixtureName(path)).toEqual(want));
});

describe("default registry", () => {
  it("has a response for every request and vice versa, with unique request_ids", async () => {
    expect(defaultRegistry.length).toBeGreaterThan(0);
    const ids: string[] = [];
    for (const pair of defaultRegistry) {
      expect(pair.loadRequest, `${pair.name} request`).toBeTypeOf("function");
      expect(pair.loadResponse, `${pair.name} response`).toBeTypeOf("function");
      const req = JSON.parse(await pair.loadRequest!()) as { request_id?: string };
      expect(req.request_id, `${pair.name} request_id`).toBeTruthy();
      ids.push(req.request_id!);
    }
    expect(new Set(ids).size).toBe(ids.length);
  });
});

describe("lookupMock", () => {
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => vi.useRealTimers());

  const files = {
    "/e/request.json": async () => '{"request_id":"a"}',
    "/e/response.json": async () => "RESP-A",
    "/e/b.request.json": async () => '{"request_id":"b"}',
    "/e/b.response.json": async () => "RESP-B",
    "/e/c.request.json": async () => '{"request_id":"c"}',
    "/e/error.json": async () => "x",
  };
  const registry = buildRegistry(files);
  const look = (id: string | undefined, signal = new AbortController().signal) =>
    lookupMock({ request_id: id } as never, { registry, signal });

  it("builds pairs, ignoring unrelated files", () => {
    expect(registry.map((p) => p.name).sort()).toEqual(["b", "c", "default"]);
  });

  it("matches by request_id after 250 ms", async () => {
    const p = look("b");
    let done = false;
    void p.then(() => (done = true));
    await vi.advanceTimersByTimeAsync(249);
    expect(done).toBe(false);
    await vi.advanceTimersByTimeAsync(1);
    expect(await p).toEqual({ ok: true, value: "RESP-B" });
  });

  it.each([["zzz"], [undefined], ["c"]])("no match for %s", async (id) => {
    const p = look(id);
    await vi.advanceTimersByTimeAsync(250);
    expect(await p).toEqual({ ok: false, error: { kind: "mock_no_match", requestId: id } });
  });

  it("cancel during the delay yields cancelled", async () => {
    const ctl = new AbortController();
    const p = look("a", ctl.signal);
    ctl.abort();
    expect(await p).toEqual({ ok: false, error: { kind: "cancelled" } });
    expect(vi.getTimerCount()).toBe(0);
  });
});
