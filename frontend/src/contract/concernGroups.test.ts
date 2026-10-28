import { describe, expect, it } from "vitest";
import schema from "@contracts/audit-response.schema.json";
import request from "@contracts/examples/request.json";
import response from "@contracts/examples/response.json";
import { CONCERN_GROUP, CONCERN_GROUP_LABELS } from "./concernGroups";
import { CONCERN_TYPES } from "./types";
import { validateRequest, validateResponse } from "./validate";

describe("concern groups", () => {
  it("matches all schema type/group clauses", () => {
    const concern = schema.$defs.Concern as any;
    expect(CONCERN_TYPES).toEqual(concern.properties.type.enum);
    expect(CONCERN_TYPES).toHaveLength(17);
    expect(concern.allOf).toHaveLength(4);
    const pairs = concern.allOf.flatMap((clause: any) =>
      clause.if.properties.type.enum.map((type: string) => [type, clause.then.properties.group.const]));
    expect(CONCERN_GROUP).toEqual(Object.fromEntries(pairs));
    expect(Object.keys(CONCERN_GROUP_LABELS)).toEqual(concern.properties.group.enum);
  });
  it.each([
    ["unsupported_claim", "changed_detail"],
    ["contradictory_evidence", "missing_context"],
    ["opinion_as_fact", "not_in_interview"],
    ["context_stripping", "opposite_of_interview"],
    ["unknown_concern", "changed_detail"],
    ["unsupported_claim", undefined],
  ])("rejects inconsistent or absent group for %s", (type, group) => {
    const req = validateRequest(request);
    if (!req.ok) throw new Error("invalid request fixture");
    const bad: any = structuredClone(response);
    const concern = bad.claims.flatMap((c: any) => c.concerns)[0];
    Object.assign(concern, { type, group });
    expect(validateResponse(bad, req.value).ok).toBe(false);
  });
});
