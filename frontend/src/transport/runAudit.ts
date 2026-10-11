import { getConfig } from "../config";
import type { AppConfig } from "../config";
import { analyzeResponse, validateRequest, validateResponse } from "../contract";
import type { AuditRequest, Result } from "../contract";
import { postAudit } from "./client";
import type { LoadError, LoadResult } from "./errors";
import { defaultRegistry, lookupMock } from "./mock/registry";
import type { MockPair } from "./mock/registry";

export interface AuditDeps {
  fetch: typeof fetch;
  config: AppConfig;
  registry: MockPair[];
  mockDelayMs?: number;
}

const defaultDeps = (): AuditDeps => ({
  fetch: (input, init) => fetch(input, init),
  config: getConfig(),
  registry: defaultRegistry,
});

const fail = <T = never>(error: LoadError): Result<T, LoadError> => ({ ok: false, error });

/** Read and validate an uploaded request file. Nothing is sent anywhere. */
export async function readRequestFile(file: Pick<File, "text">): Promise<Result<AuditRequest, LoadError>> {
  let text: string;
  try {
    text = (await file.text()).replace(/^\uFEFF/, "");
  } catch {
    return fail({ kind: "invalid_request_file", reason: "not_json", message: "the file could not be read" });
  }
  if (text.trim() === "") return fail({ kind: "invalid_request_file", reason: "empty" });
  let raw: unknown;
  try {
    raw = JSON.parse(text);
  } catch (e) {
    return fail({ kind: "invalid_request_file", reason: "not_json", message: e instanceof Error ? e.message : String(e) });
  }
  const checked = validateRequest(raw);
  if (!checked.ok) return fail({ kind: "invalid_request_file", reason: "schema", issues: checked.error });
  return checked;
}

/** Send (or mock-look-up) an already validated request and validate the reply. */
export async function auditRequest(
  request: AuditRequest,
  opts: { signal: AbortSignal; deps?: AuditDeps },
): Promise<Result<LoadResult, LoadError>> {
  const deps = opts.deps ?? defaultDeps();
  const { mock, auditUrl } = deps.config;
  if (!mock && !auditUrl) return fail({ kind: "config_missing" });

  let body: Result<string, LoadError>;
  try {
    body = mock
      ? await lookupMock(request, { registry: deps.registry, signal: opts.signal, delayMs: deps.mockDelayMs })
      : await postAudit(auditUrl!, request, { fetch: deps.fetch, signal: opts.signal });
  } catch {
    // A lazy fixture chunk failed to load.
    return fail({ kind: "network", url: "bundled mock fixtures" });
  }
  if (!body.ok) return body;

  if (body.value.trim() === "") return fail({ kind: "invalid_response", reason: "empty" });
  let raw: unknown;
  try {
    raw = JSON.parse(body.value);
  } catch (e) {
    return fail({ kind: "invalid_response", reason: "not_json", message: e instanceof Error ? e.message : String(e) });
  }
  const checked = validateResponse(raw, request);
  if (!checked.ok) {
    const e = checked.error;
    if (e.kind === "request_id_mismatch") return fail(e);
    if (e.kind === "schema") return fail({ kind: "invalid_response", reason: "schema", issues: e.issues });
    if (e.kind === "duplicate_claim_id") return fail({ kind: "invalid_response", reason: "duplicate_claim_id", claimId: e.id });
    if (e.kind === "duplicate_evidence_id") {
      return fail({ kind: "invalid_response", reason: "duplicate_evidence_id", claimId: e.claimId, evidenceId: e.id });
    }
    return fail({ kind: "invalid_response", reason: e.kind });
  }
  return {
    ok: true,
    value: {
      ok: true,
      request,
      response: checked.value,
      analysis: analyzeResponse(request, checked.value),
      source: mock ? "mock" : "service",
    },
  };
}

export async function runAudit(
  file: Pick<File, "text">,
  opts: { signal: AbortSignal; deps?: AuditDeps },
): Promise<Result<LoadResult, LoadError>> {
  const request = await readRequestFile(file);
  if (!request.ok) return request;
  return auditRequest(request.value, opts);
}
