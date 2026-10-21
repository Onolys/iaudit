import { expect, it } from "vitest";
import schema from "@eval-api/eval-api.schema.json";

it("imports the eval API schema in place through @eval-api", () => {
  expect(schema.$id).toBe("https://iaudit.local/schemas/eval-api.schema.json");
  expect(schema.$defs).toHaveProperty("BackendHealth");
});
