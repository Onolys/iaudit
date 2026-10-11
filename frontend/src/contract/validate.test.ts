import { describe, expect, it } from "vitest";
import requestExample from "@contracts/examples/request.json";
import responseExample from "@contracts/examples/response.json";
import { validateRequest, validateResponse } from "./validate";
import type { AuditRequest } from "./types";

const clone = <T,>(v: T): T => structuredClone(v);
const req = () => clone(requestExample) as unknown as AuditRequest;
const res = (): any => clone(responseExample);

describe("validateRequest", () => {
  it("accepts the example", () => {
    expect(validateRequest(requestExample).ok).toBe(true);
  });
  it("reports raw ajv path and message", () => {
    const bad: any = clone(requestExample);
    delete bad.transcript;
    const r = validateRequest(bad);
    expect(r.ok).toBe(false);
    if (!r.ok) {
      expect(r.error[0].path).toBe("/");
      expect(r.error[0].message).toContain("transcript");
    }
  });
});

describe("validateResponse", () => {
  it("accepts the example pair", () => {
    const r = validateResponse(responseExample, req());
    expect(r.ok).toBe(true);
  });
  it.each([null, [], "x", 3])("rejects non-object %j", (v) => {
    const r = validateResponse(v, req());
    expect(r).toEqual({ ok: false, error: { kind: "not_object" } });
  });
  it("rejects wrong version before schema", () => {
    const bad = res();
    bad.schema_version = "2.0.0";
    bad.extra = 1;
    expect(validateResponse(bad, req())).toEqual({ ok: false, error: { kind: "wrong_version" } });
  });
  it("reports schema issues with path and message", () => {
    const bad = res();
    bad.extra = 1;
    const r = validateResponse(bad, req());
    expect(r.ok).toBe(false);
    if (!r.ok && r.error.kind === "schema") {
      expect(r.error.issues[0].path).toBe("/");
      expect(r.error.issues[0].message).toContain("additional");
    } else throw new Error("expected schema error");
  });
  it("rejects contradicted claim without contradicting evidence", () => {
    const bad = res();
    bad.claims[1].evidence = [];
    const r = validateResponse(bad, req());
    expect(r.ok === false && r.error.kind).toBe("schema");
  });
  it("detects request_id mismatch", () => {
    const bad = res();
    bad.request_id = "other";
    expect(validateResponse(bad, req())).toEqual({
      ok: false,
      error: { kind: "request_id_mismatch", expected: "example-001", received: "other" },
    });
    delete bad.request_id;
    const r = validateResponse(bad, req());
    expect(r.ok === false && r.error.kind).toBe("request_id_mismatch");
  });
  it("ignores response id when request has none", () => {
    const rq = req();
    delete rq.request_id;
    expect(validateResponse(res(), rq).ok).toBe(true);
  });
  it("rejects duplicate claim ids", () => {
    const bad = res();
    bad.claims[1].id = bad.claims[0].id;
    expect(validateResponse(bad, req())).toEqual({
      ok: false,
      error: { kind: "duplicate_claim_id", id: "c-supported" },
    });
  });
});
