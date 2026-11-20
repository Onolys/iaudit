import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import Ajv2020 from "ajv/dist/2020";
import { describe, expect, it } from "vitest";
import { edgeReport, noRatingReport, noTipsReport, reasonsFailedReport, sampleReport } from ".";

/** Validates every report fixture against the real contract (SP03 report.schema.json). */
const repoRoot = resolve(__dirname, "../../../..");
const schema = JSON.parse(readFileSync(resolve(repoRoot, "engines/evaluation/schemas/report.schema.json"), "utf8"));
const ajv = new Ajv2020({ allErrors: true, strict: false });
const validate = ajv.compile(schema);

const packFixture = (name: string): unknown =>
  JSON.parse(readFileSync(resolve(repoRoot, `protocols/miti-4.2.1/fixtures/evaluation/${name}`), "utf8"));

const fixtures: [string, unknown][] = [
  ["sample (N=1, rated)", sampleReport],
  ["no-rating", noRatingReport],
  ["reasons_audit failed", reasonsFailedReport],
  ["no tips", noTipsReport],
  ["utf-8 edge", edgeReport],
  ["pack report_full.json", packFixture("report_full.json")],
  ["pack report_partial.json", packFixture("report_partial.json")],
  ["pack report_no_rating.json", packFixture("report_no_rating.json")],
];

describe.each(fixtures)("report.schema.json validates: %s", (_name, report) => {
  it("is valid", () => {
    const ok = validate(report);
    expect(ok ? [] : validate.errors?.map((e) => `${e.instancePath} ${e.message}`)).toEqual([]);
  });
});

describe("validator sanity", () => {
  it("rejects an unknown extra field (additionalProperties: false)", () => {
    expect(validate({ ...(sampleReport as object), bogus: 1 })).toBe(false);
  });
});
