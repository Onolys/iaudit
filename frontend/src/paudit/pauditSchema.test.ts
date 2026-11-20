import Ajv2020 from "ajv/dist/2020";
import { describe, expect, it } from "vitest";
import schema from "@paudit-schema/paudit-result.schema.json";
import sample from "./fixtures/sample-result.json";
import { RESULT_KEYS } from "./types";

type Def = { properties?: Record<string, unknown>; required?: string[] };
const defs = schema.$defs as Record<string, Def>;

describe("paudit result types vs engines/paudit/schemas/paudit-result.schema.json", () => {
  it("imports the schema in place through @paudit-schema", () => {
    expect(schema.title).toBe("PauditResult");
    expect(defs).toHaveProperty("RunResult");
  });

  it("the sample result validates against the schema", () => {
    const ajv = new Ajv2020({ allErrors: true, allowUnionTypes: true, strict: false });
    const ok = ajv.validate(schema, sample);
    expect(ajv.errors ?? []).toEqual([]);
    expect(ok).toBe(true);
  });

  it("the top-level keys match", () => {
    expect([...RESULT_KEYS.PauditResult.all].sort()).toEqual(Object.keys(schema.properties).sort());
    expect([...RESULT_KEYS.PauditResult.required].sort()).toEqual([...schema.required].sort());
  });

  for (const [name, keys] of Object.entries(RESULT_KEYS)) {
    if (name === "PauditResult") continue;
    it(`${name}: property names and required set match the schema`, () => {
      const def = defs[name];
      expect(def, `schema has $defs.${name}`).toBeTruthy();
      expect([...keys.all].sort()).toEqual(Object.keys(def.properties ?? {}).sort());
      expect([...keys.required].sort()).toEqual([...(def.required ?? [])].sort());
    });
  }
});
