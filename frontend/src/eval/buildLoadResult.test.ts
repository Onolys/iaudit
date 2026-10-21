import { afterEach, expect, it, vi } from "vitest";
import request from "@contracts/examples/request.json";
import response from "@contracts/examples/response.json";
import { buildLoadResult } from "./buildLoadResult";

afterEach(() => vi.unstubAllGlobals());

it("replays a parsed contract example with service source and analyzed claims", () => {
  const result = buildLoadResult(request, response);
  expect(result.ok).toBe(true);
  if (!result.ok) throw new Error("expected a valid replay");
  expect(result.value.request).toBe(request);
  expect(result.value.response).toBe(response);
  expect(result.value.ok).toBe(true);
  expect(result.value.source).toBe("service");
  expect(result.value.analysis.counts.overall).toEqual({
    supported: 1, contradicted: 1, partially_supported: 1, insufficient_evidence: 1, out_of_scope: 1,
  });
  expect(result.value.analysis.checks["c-supported"].claimSpanOk).toBe(true);
});

it("rejects stale 1.0.0 data with the Audit wrong-version error", () => {
  expect(buildLoadResult(request, { ...response, schema_version: "1.0.0" })).toEqual({
    ok: false, error: { kind: "invalid_response", reason: "wrong_version" },
  });
});

it("rejects malformed saved responses with validation issues", () => {
  const result = buildLoadResult(request, { ...response, claims: "invalid" });
  expect(result).toMatchObject({ ok: false, error: { kind: "invalid_response", reason: "schema" } });
  if (result.ok || result.error.kind !== "invalid_response") throw new Error("expected response error");
  expect(result.error.issues).toEqual(expect.arrayContaining([expect.objectContaining({ path: "/claims" })]));
});

it("validates a bad request before checking even a stale response", () => {
  const result = buildLoadResult({}, { schema_version: "1.0.0" });
  expect(result).toMatchObject({ ok: false, error: { kind: "invalid_request_file", reason: "schema" } });
  if (result.ok || result.error.kind !== "invalid_request_file") throw new Error("expected request error");
  expect(result.error.issues?.length).toBeGreaterThan(0);
});

it("enforces the saved request ID through the shared response checks", () => {
  expect(buildLoadResult(request, { ...response, request_id: "other" })).toEqual({
    ok: false, error: { kind: "request_id_mismatch", expected: "example-001", received: "other" },
  });
});

it("does not fetch or parse JSON while building a valid replay", () => {
  const fetchSpy = vi.fn(() => { throw new Error("unexpected network"); });
  vi.stubGlobal("fetch", fetchSpy);
  const parseSpy = vi.spyOn(JSON, "parse");
  let result;
  let parseCalls;
  try {
    result = buildLoadResult(request, response);
    parseCalls = parseSpy.mock.calls.length;
  } finally {
    parseSpy.mockRestore();
  }
  expect(result.ok).toBe(true);
  expect(fetchSpy).not.toHaveBeenCalled();
  expect(parseCalls).toBe(0);
});
