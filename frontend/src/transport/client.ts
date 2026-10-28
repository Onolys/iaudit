import type { AuditRequest, Result } from "../contract";
import { retry } from "../utils/retry";
import { readErrorBody } from "./errorBody";
import type { LoadError } from "./errors";

export const TIMEOUT_MS = 120_000;

export interface PostDeps {
  fetch: typeof fetch;
  signal: AbortSignal;
}

/** POST the request; resolves to the response body text on 2xx. Never throws. */
export async function postAudit(
  url: string,
  request: AuditRequest,
  { fetch: doFetch, signal }: PostDeps,
): Promise<Result<string, LoadError>> {
  if (signal.aborted) return { ok: false, error: { kind: "cancelled" } };

  const controller = new AbortController();
  let reason: "timeout" | "cancelled" | undefined;
  const abort = (why: "timeout" | "cancelled") => {
    reason ??= why;
    controller.abort();
  };
  const onCancel = () => abort("cancelled");
  signal.addEventListener("abort", onCancel);
  const timer = setTimeout(() => abort("timeout"), TIMEOUT_MS);

  try {
    const res = await retry(() => doFetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      credentials: "omit",
      body: JSON.stringify(request),
      signal: controller.signal,
    }), {
      attempts: 2, delayMs: 300, signal: controller.signal,
      shouldRetry: outcome => outcome.ok && outcome.value.status === 429,
    });
    const text = await res.text();
    if (res.ok) return { ok: true, value: text };
    const body = readErrorBody(text);
    const validBody = body?.status === res.status ? body : undefined;
    const kind = res.status >= 400 && res.status < 500 ? "http_4xx" : "http_5xx";
    return { ok: false, error: { kind, status: res.status, message: validBody?.message, details: validBody?.details } };
  } catch {
    if (reason === "timeout") return { ok: false, error: { kind: "timeout", seconds: TIMEOUT_MS / 1000 } };
    if (reason === "cancelled") return { ok: false, error: { kind: "cancelled" } };
    return { ok: false, error: { kind: "network", url } };
  } finally {
    clearTimeout(timer);
    signal.removeEventListener("abort", onCancel);
  }
}
