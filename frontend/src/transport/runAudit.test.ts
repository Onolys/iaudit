import { readFileSync } from "node:fs";
import { describe, expect, it, vi } from "vitest";
import type { AppConfig } from "../config";
import { defaultRegistry } from "./mock/registry";
import { auditRequest, readRequestFile, runAudit } from "./runAudit";
import type { LoadError } from "./errors";

const example = (name: string) =>
  readFileSync(new URL(`../../../docs/contracts/examples/${name}.json`, import.meta.url), "utf8");
const requestText = example("request");
const responseText = example("response");
const file = (text: string) => new File([text], "r.json");

const real: AppConfig = { mock: false, auditUrl: "https://audit.example/api" };
const mockCfg: AppConfig = { mock: true, auditUrl: null };

function setup(config: AppConfig, body = responseText, status = 200) {
  const fetchSpy = vi.fn(async () => new Response(body, { status }));
  return {
    fetchSpy,
    run: (f: File | string) =>
      runAudit(typeof f === "string" ? file(f) : f, {
        signal: new AbortController().signal,
        deps: { fetch: fetchSpy as unknown as typeof fetch, config, registry: defaultRegistry, mockDelayMs: 0 },
      }),
  };
}

async function errorOf(p: Promise<{ ok: boolean }>): Promise<LoadError> {
  const r = (await p) as { ok: boolean; error?: LoadError };
  if (r.ok) throw new Error("expected error");
  return r.error!;
}

describe("readRequestFile", () => {
  it("parses a valid request, tolerating a BOM", async () => {
    const r = await readRequestFile(file("\uFEFF" + requestText));
    expect(r.ok).toBe(true);
  });
  it.each(["", "  \n "])("empty %j", async (t) => {
    const r = await readRequestFile(file(t));
    expect(r).toEqual({ ok: false, error: { kind: "invalid_request_file", reason: "empty" } });
  });
  it("not json", async () => {
    const r = await readRequestFile(file("{nope"));
    expect(r).toMatchObject({ ok: false, error: { kind: "invalid_request_file", reason: "not_json" } });
  });
  it("schema failure lists issues", async () => {
    const r = await readRequestFile(file("{}"));
    expect(r).toMatchObject({ ok: false, error: { kind: "invalid_request_file", reason: "schema" } });
    expect((r as { error: { issues: unknown[] } }).error.issues.length).toBeGreaterThan(0);
  });
});

describe("invalid files never reach fetch", () => {
  it.each(["", "{nope", "{}", '{"schema_version":"1.0.0"}'])("%j", async (t) => {
    const { run, fetchSpy } = setup(real);
    expect((await errorOf(run(t))).kind).toBe("invalid_request_file");
    expect(fetchSpy).not.toHaveBeenCalled();
  });
});

describe("config", () => {
  it("config_missing without url and without mock", async () => {
    const { run, fetchSpy } = setup({ mock: false, auditUrl: null });
    expect(await errorOf(run(requestText))).toEqual({ kind: "config_missing" });
    expect(fetchSpy).not.toHaveBeenCalled();
  });
});

describe("mock mode", () => {
  it("serves examples/request.json without fetch", async () => {
    const { run, fetchSpy } = setup(mockCfg);
    const r = await run(requestText);
    expect(r).toMatchObject({ ok: true, value: { source: "mock" } });
    expect(fetchSpy).not.toHaveBeenCalled();
  });
  it("unknown request_id -> mock_no_match", async () => {
    const { run } = setup(mockCfg);
    const req = { ...JSON.parse(requestText), request_id: "nope-123" };
    expect(await errorOf(run(JSON.stringify(req)))).toEqual({ kind: "mock_no_match", requestId: "nope-123" });
  });
  it("missing request_id -> mock_no_match", async () => {
    const { run } = setup(mockCfg);
    const { request_id: _drop, ...req } = JSON.parse(requestText);
    expect(await errorOf(run(JSON.stringify(req)))).toEqual({ kind: "mock_no_match", requestId: undefined });
  });
});

describe("real service", () => {
  it("returns ok with source service and analysis", async () => {
    const { run, fetchSpy } = setup(real);
    const r = await run(requestText);
    expect(r).toMatchObject({ ok: true, value: { source: "service" } });
    expect((r as { value: { analysis: unknown } }).value.analysis).toBeTruthy();
    expect(fetchSpy).toHaveBeenCalledTimes(1);
  });

  const mutate = (fn: (r: Record<string, unknown>) => void) => {
    const r = JSON.parse(responseText) as Record<string, unknown>;
    fn(r);
    return JSON.stringify(r);
  };
  const cases: [string, string, Partial<LoadError>][] = [
    ["empty body", "", { kind: "invalid_response", reason: "empty" }],
    ["non-JSON body", "<html>", { kind: "invalid_response", reason: "not_json" }],
    ["array body", "[]", { kind: "invalid_response", reason: "not_object" }],
    ["version 2.0.0", mutate((r) => (r.schema_version = "2.0.0")), { kind: "invalid_response", reason: "wrong_version" }],
    ["extra field", mutate((r) => (r.extra = 1)), { kind: "invalid_response", reason: "schema" }],
    ["id mismatch", mutate((r) => (r.request_id = "other")), { kind: "request_id_mismatch", expected: "example-001", received: "other" }],
    [
      "duplicate claim id",
      mutate((r) => {
        const claims = r.claims as { id: string }[];
        claims.push(structuredClone(claims[0]));
      }),
      { kind: "invalid_response", reason: "duplicate_claim_id" },
    ],
  ];
  it.each(cases)("rejects %s", async (_n, body, want) => {
    const { run } = setup(real, body);
    expect(await errorOf(run(requestText))).toMatchObject(want);
  });

  it("maps http errors", async () => {
    const { run } = setup(real, "x", 503);
    expect(await errorOf(run(requestText))).toMatchObject({ kind: "http_5xx", status: 503 });
  });
});

describe("auditRequest", () => {
  it("can resend a stored request", async () => {
    const { fetchSpy } = setup(real);
    const request = JSON.parse(requestText);
    const deps = { fetch: fetchSpy as unknown as typeof fetch, config: real, registry: defaultRegistry, mockDelayMs: 0 };
    await auditRequest(request, { signal: new AbortController().signal, deps });
    await auditRequest(request, { signal: new AbortController().signal, deps });
    expect(fetchSpy).toHaveBeenCalledTimes(2);
  });
});
