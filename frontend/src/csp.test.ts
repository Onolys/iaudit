import { afterEach, expect, it, vi } from "vitest";

// The admin Hosting CSP has no 'unsafe-eval' (frontend/firebase.json), so nothing that ships in the
// browser may call `new Function` / eval. Ajv's runtime compile() does; validators must be precompiled.
afterEach(() => vi.unstubAllGlobals());

function forbidCodegen() {
  const blocked = function () {
    throw new EvalError("Refused to evaluate a string as JavaScript (CSP: no 'unsafe-eval')");
  };
  vi.stubGlobal("Function", blocked);
  vi.stubGlobal("eval", blocked);
}

it("runs every runtime validator without new Function/eval", async () => {
  forbidCodegen();
  const { validateRequest, validateResponse } = await import("./contract/validate");
  const { readErrorBody } = await import("./transport/errorBody");
  const paudit = await import("./paudit/pauditApi");
  const { createEvalApi } = await import("./eval/evalApi");

  expect(validateRequest({}).ok).toBe(false);
  expect(validateResponse({}, { request_id: "r" } as never).ok).toBe(false);
  expect(readErrorBody("{}")).toBeUndefined();
  expect(readErrorBody(JSON.stringify({ schema_version: "0.0.2", status: 400, message: "m", details: [{ code: "internal_error", message: "d" }] }))).toEqual({ status: 400, message: "m", details: [{ code: "internal_error", message: "d" }] });

  const json = (status: number, body: unknown) => (async () => new Response(JSON.stringify(body), { status })) as typeof fetch;
  const bad = await createEvalApi({ fetch: json(200, { nope: 1 }) }).health();
  expect(bad).toMatchObject({ ok: false, error: { kind: "bad_body" } });
  const err = await createEvalApi({ fetch: json(404, { error: { code: "not_found", message: "x" } }) }).getRun("r1");
  expect(err).toMatchObject({ ok: false, error: { kind: "api", status: 404 } });
  const list = await createEvalApi({ fetch: json(200, []) }).listRuns();
  expect(list).toEqual({ ok: true, value: [] });

  const res = await paudit.runPaudit({ fetch: json(200, { nope: 1 }), config: { mock: false, auditUrl: "http://x/v1/audit" } }, {} as never, new AbortController().signal);
  expect(res).toMatchObject({ ok: false, message: expect.stringContaining("does not match") });
}, 20000);
