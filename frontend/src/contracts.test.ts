import { describe, expect, it } from "vitest";
import requestSchema from "@contracts/audit-request.schema.json";
import responseSchema from "@contracts/audit-response.schema.json";
import example from "@contracts/examples/response.json";

describe("@contracts alias", () => {
  it("imports both schemas and the response example in place", () => {
    expect(requestSchema).toBeTypeOf("object");
    expect(responseSchema).toBeTypeOf("object");
    expect(example.schema_version).toBe("1.1.0");
  });
});
