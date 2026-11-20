import { describe, expect, it } from "vitest";
import { analyzeResponse, validateRequest, validateResponse } from "../contract";
import type { AuditRequest, AuditResponse } from "../contract";

const files = import.meta.glob("../../../docs/contracts/examples/*.json", {
  query: "?raw",
  import: "default",
  eager: true,
}) as Record<string, string>;

const FIXTURE = /^(?:(.+)\.)?(request|response)\.json$/;
const pairs = new Map<string, { request?: string; response?: string }>();
for (const [path, text] of Object.entries(files)) {
  const m = FIXTURE.exec(path.slice(path.lastIndexOf("/") + 1));
  if (!m) continue; // e.g. error.json
  const pair = pairs.get(m[1] ?? "default") ?? {};
  pair[m[2] as "request" | "response"] = text;
  pairs.set(m[1] ?? "default", pair);
}

/** Claim ids whose spans are expected to be flagged; every other pair has none. */
const FLAGGED: Record<string, string[]> = { default: [], partial: [], "no-speaker": [], "out-of-range": ["c-bad"] };

describe("mock fixtures", () => {
  it("covers exactly the expected pairs", () => {
    expect([...pairs.keys()].sort()).toEqual(Object.keys(FLAGGED).sort());
  });

  it("has no orphan request or response file", () => {
    for (const [name, pair] of pairs) {
      expect(pair.request, `${name} request`).toBeDefined();
      expect(pair.response, `${name} response`).toBeDefined();
    }
  });

  it("uses a unique request_id per pair", () => {
    const ids = [...pairs.values()].map((p) => JSON.parse(p.request!).request_id);
    expect(ids.every((id) => typeof id === "string")).toBe(true);
    expect(new Set(ids).size).toBe(ids.length);
  });

  describe.each(Object.keys(FLAGGED))("%s", (name) => {
    const pair = pairs.get(name)!;
    const request = validateRequest(JSON.parse(pair.request!));
    it("request validates", () => {
      expect(request.ok).toBe(true);
    });
    it("response validates against its request", () => {
      const r = validateResponse(JSON.parse(pair.response!), request.ok ? request.value : (undefined as never));
      expect(r.ok, JSON.stringify(r.ok ? "" : r.error)).toBe(true);
    });
    it("flags exactly the expected claims", () => {
      const req = JSON.parse(pair.request!) as AuditRequest;
      const res = JSON.parse(pair.response!) as AuditResponse;
      const analysis = analyzeResponse(req, res);
      const flagged = res.claims.filter((c) => analysis.checks[c.id].spanOutOfRange).map((c) => c.id);
      expect(flagged).toEqual(FLAGGED[name]);
    });
  });

  it("default has one claim per verdict", () => {
    const res = JSON.parse(pairs.get("default")!.response!) as AuditResponse;
    expect(res.claims).toHaveLength(5);
    expect(new Set(res.claims.map((c) => c.verdict)).size).toBe(5);
  });

  it("partial is partial with a not-processed section and a second warning", () => {
    const res = JSON.parse(pairs.get("partial")!.response!) as AuditResponse;
    expect(res.status).toBe("partial");
    expect(res.warnings.map((w) => w.code).sort()).toEqual(["ambiguous_speaker", "section_not_processed"]);
    expect(res.claims.every((c) => c.span.start.index === 0)).toBe(true);
  });

  it("out-of-range flags only the claim past the section text", () => {
    const res = JSON.parse(pairs.get("out-of-range")!.response!) as AuditResponse;
    expect(res.claims).toHaveLength(3);
  });
});
