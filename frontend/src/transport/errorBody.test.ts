import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import { readErrorBody } from "./errorBody";

const example = (name: string) => JSON.parse(readFileSync(
  new URL(`../../../docs/contracts/examples/${name}.json`, import.meta.url), "utf8",
));

describe("readErrorBody", () => {
  it.each(["error", "multi-error"])("returns validated status, message and details from %s", name => {
    const { status, message, details } = example(name);
    expect(readErrorBody(JSON.stringify(example(name)))).toEqual({ status, message, details });
  });

  it.each(["", "<html>upstream failed</html>", "null", "[]", "{}",
    JSON.stringify({ schema_version: "0.0.1", error: { code: "internal_error", message: "old" } }),
  ])("rejects invalid or old bodies %j", text => {
    expect(readErrorBody(text)).toBeUndefined();
  });

  it.each([
    { schema_version: "9.8.7" }, { status: 399 }, { status: 600 }, { status: 400.5 },
    { message: "" }, { details: [] }, { details: [{ code: "other", message: "wrong" }] },
    { details: [{ code: "internal_error", message: "" }] },
    { error: { code: "internal_error", message: "extra old field" } },
  ])("rejects invalid fields %j", patch => {
    expect(readErrorBody(JSON.stringify({ ...example("error"), ...patch }))).toBeUndefined();
  });

  it("accepts an error without a request id", () => {
    const body = example("error");
    delete body.request_id;
    expect(readErrorBody(JSON.stringify(body))).toMatchObject({ status: 400 });
  });

  it.each(["schema_version", "status", "message", "details"])("requires %s", field => {
    const body = example("error");
    delete body[field];
    expect(readErrorBody(JSON.stringify(body))).toBeUndefined();
  });
});
