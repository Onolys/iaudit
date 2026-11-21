import { describe, expect, it } from "vitest";
import { buildCard, emptyForm, type RatingForm } from "../features/rating/card";
import schema from "./rating.schema.json";
import { COUNTS, GLOBALS, LIMITS } from "./miti-items";

type Schema = { type?: string | string[]; properties?: Record<string, Schema>; additionalProperties?: boolean; minimum?: number; maximum?: number; maxLength?: number };

/** Tiny validator for the subset of JSON Schema the rating schema uses; returns violation paths. */
function check(value: unknown, s: Schema, path = ""): string[] {
  const out: string[] = [];
  const types = s.type === undefined ? [] : Array.isArray(s.type) ? s.type : [s.type];
  const kind = value === null ? "null" : Array.isArray(value) ? "array" : typeof value === "number" ? (Number.isInteger(value) ? "integer" : "number") : typeof value;
  const ok = types.length === 0 || types.includes(kind) || (kind === "integer" && types.includes("number"));
  if (!ok) return [`${path}: type ${kind}`];
  if (typeof value === "number") {
    if (s.minimum !== undefined && value < s.minimum) out.push(`${path}: minimum`);
    if (s.maximum !== undefined && value > s.maximum) out.push(`${path}: maximum`);
  }
  if (typeof value === "string" && s.maxLength !== undefined && [...value].length > s.maxLength) out.push(`${path}: maxLength`);
  if (value && typeof value === "object" && !Array.isArray(value)) {
    for (const [k, v] of Object.entries(value)) {
      const sub = s.properties?.[k];
      if (!sub) {
        if (s.additionalProperties === false) out.push(`${path}.${k}: unknown key`);
        continue;
      }
      out.push(...check(v, sub, path ? `${path}.${k}` : k));
    }
  }
  return out;
}

const S = schema as unknown as Schema;
const fullForm = (): RatingForm => {
  const f = emptyForm();
  f.changeGoal = "g";
  f.spanFrom = "01:05";
  f.spanTo = "12:30";
  for (const g of GLOBALS) f.globals[g.id] = { score: "4", reason: "r", exTime: "02:10", exText: "e" };
  for (const c of COUNTS) f.counts[c.id] = { count: "3", note: "n" };
  f.notes = "notes";
  return f;
};

describe("miti-items parity with rating.schema.json", () => {
  it("lists exactly the schema's four globals and ten behaviour codes", () => {
    expect(GLOBALS.map((g) => g.id).sort()).toEqual(Object.keys(S.properties!.globals.properties!).sort());
    expect(COUNTS.map((c) => c.id).sort()).toEqual(Object.keys(S.properties!.counts.properties!).sort());
    expect(GLOBALS).toHaveLength(4);
    expect(COUNTS).toHaveLength(10);
  });

  it("has a label and five anchors for every global and a label for every code", () => {
    for (const g of GLOBALS) {
      expect(g.label).not.toBe("");
      expect(g.anchors).toHaveLength(5);
    }
    for (const c of COUNTS) expect(c.label).not.toBe("");
  });

  it("uses the schema's character limits", () => {
    const g = S.properties!.globals.properties!.cct.properties!;
    expect(g.reason.maxLength).toBe(LIMITS.item);
    expect(g.example.properties!.text.maxLength).toBe(LIMITS.item);
    expect(S.properties!.counts.properties!.gi.properties!.note.maxLength).toBe(LIMITS.item);
    expect(S.properties!.notes.maxLength).toBe(LIMITS.notes);
    expect([LIMITS.item, LIMITS.notes]).toEqual([1000, 3000]);
  });

  it("builds cards the schema accepts, full and empty", () => {
    expect(check(buildCard(fullForm()), S)).toEqual([]);
    expect(check(buildCard(emptyForm()), S)).toEqual([]);
    expect(check(buildCard(emptyForm(), { noRating: true }), S)).toEqual([]);
  });

  it("the validator itself rejects unknown keys and long text (guards the check)", () => {
    expect(check({ change_goal: "g", extra: 1 }, S)).toContain(".extra: unknown key");
    expect(check({ notes: "x".repeat(3001) }, S)).toEqual(["notes: maxLength"]);
  });
});
