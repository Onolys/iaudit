import { checkResult } from "../generated/paudit";
import type { AppConfig } from "../config";
import { readErrorBody, type ErrorDetail } from "../transport/errorBody";
import sampleResult from "./fixtures/sample-result.json";
import mockTranscript from "./fixtures/good_practice.transcript.json";
import mockParams from "./fixtures/good_practice.params.json";
import type { Fixture, FixtureSummary, PauditRequest, PauditResult, PauditTranscript } from "./types";

export const PACK_REF = "miti@4.2.1";
export const TIMEOUT_MS = 130_000;

export interface PauditDeps {
  fetch: typeof fetch;
  config: Pick<AppConfig, "mock" | "auditUrl">;
  mockDelayMs?: number;
}

export type ApiResult<T> =
  | { ok: true; value: T }
  | { ok: false; message: string; details?: ErrorDetail[] };

const MOCK_FIXTURE: Fixture = {
  name: "good_practice",
  description: String((mockTranscript as { description?: string }).description ?? ""),
  pack: PACK_REF,
  transcript: mockTranscript as unknown as PauditTranscript,
  params: mockParams as Fixture["params"],
};

/** `.../v1/audit` -> `.../v1/paudit`; any other URL falls back to `/v1/paudit` on its origin. */
export function pauditUrl(auditUrl: string): string {
  if (/\/audit\/?$/.test(auditUrl)) return auditUrl.replace(/\/audit\/?$/, "/paudit");
  return new URL("/v1/paudit", auditUrl).toString();
}

const sleep = (ms: number) => (ms > 0 ? new Promise<void>(r => setTimeout(r, ms)) : Promise.resolve());

async function send(
  deps: PauditDeps, url: string, init: RequestInit, signal: AbortSignal,
): Promise<ApiResult<unknown>> {
  const controller = new AbortController();
  let timedOut = false;
  const onAbort = () => controller.abort();
  signal.addEventListener("abort", onAbort);
  const timer = setTimeout(() => { timedOut = true; controller.abort(); }, TIMEOUT_MS);
  try {
    const res = await deps.fetch(url, { ...init, credentials: "omit", signal: controller.signal });
    const text = await res.text();
    if (res.ok) {
      try {
        return { ok: true, value: JSON.parse(text) };
      } catch {
        return { ok: false, message: "The service reply was not valid JSON." };
      }
    }
    const body = readErrorBody(text);
    return {
      ok: false,
      message: body?.status === res.status ? body.message : `The service returned HTTP ${res.status}.`,
      details: body?.status === res.status ? body.details : undefined,
    };
  } catch {
    if (signal.aborted) return { ok: false, message: "Cancelled." };
    return { ok: false, message: timedOut ? "The request timed out." : "Could not reach the paudit service." };
  } finally {
    clearTimeout(timer);
    signal.removeEventListener("abort", onAbort);
  }
}

function baseUrl(deps: PauditDeps): string | null {
  return deps.config.auditUrl ? pauditUrl(deps.config.auditUrl) : null;
}

const NOT_CONFIGURED = { ok: false as const, message: "Audit service not configured: VITE_AUDIT_URL is not set and mock mode is off." };

export async function listFixtures(deps: PauditDeps, signal: AbortSignal): Promise<ApiResult<FixtureSummary[]>> {
  if (deps.config.mock) {
    const f = MOCK_FIXTURE;
    return { ok: true, value: [{ name: f.name, description: f.description, pack: f.pack, turns: f.transcript.turns.length, params: f.params }] };
  }
  const base = baseUrl(deps);
  if (!base) return NOT_CONFIGURED;
  const r = await send(deps, `${base}/fixtures`, { method: "GET", headers: { Accept: "application/json" } }, signal);
  if (!r.ok) return r;
  const list = (r.value as { fixtures?: unknown }).fixtures;
  return Array.isArray(list) ? { ok: true, value: list as FixtureSummary[] } : { ok: false, message: "Unexpected fixtures reply." };
}

export async function getFixture(deps: PauditDeps, name: string, signal: AbortSignal): Promise<ApiResult<Fixture>> {
  if (deps.config.mock) {
    return name === MOCK_FIXTURE.name ? { ok: true, value: MOCK_FIXTURE } : { ok: false, message: "Fixture not found." };
  }
  const base = baseUrl(deps);
  if (!base) return NOT_CONFIGURED;
  const r = await send(deps, `${base}/fixtures/${encodeURIComponent(name)}`, { method: "GET", headers: { Accept: "application/json" } }, signal);
  if (!r.ok) return r;
  const f = r.value as Partial<Fixture>;
  return f?.transcript && f.params ? { ok: true, value: f as Fixture } : { ok: false, message: "Unexpected fixture reply." };
}

export async function runPaudit(deps: PauditDeps, request: PauditRequest, signal: AbortSignal): Promise<ApiResult<PauditResult>> {
  if (deps.config.mock) {
    await sleep(deps.mockDelayMs ?? 250);
    return { ok: true, value: sampleResult as unknown as PauditResult };
  }
  const base = baseUrl(deps);
  if (!base) return NOT_CONFIGURED;
  const r = await send(deps, base, {
    method: "POST",
    headers: { "Content-Type": "application/json", Accept: "application/json" },
    body: JSON.stringify(request),
  }, signal);
  if (!r.ok) return r;
  if (!checkResult(r.value)) return { ok: false, message: "The service reply does not match the paudit result schema." };
  return { ok: true, value: r.value as unknown as PauditResult };
}

/** Parse pasted/uploaded transcript JSON. Error messages never echo transcript text. */
export function parseTranscript(text: string): ApiResult<PauditTranscript> {
  let raw: unknown;
  try {
    raw = JSON.parse(text.replace(/^﻿/, ""));
  } catch {
    return { ok: false, message: "The transcript is not valid JSON." };
  }
  const turns = (raw as { turns?: unknown } | null)?.turns;
  const ok = Array.isArray(turns) && turns.length > 0 && turns.every(t =>
    t && typeof t === "object" && typeof (t as { id?: unknown }).id === "string"
      && typeof (t as { speaker?: unknown }).speaker === "string" && typeof (t as { text?: unknown }).text === "string");
  return ok ? { ok: true, value: raw as PauditTranscript } : { ok: false, message: "The transcript needs a non-empty turns list, each with id, speaker and text." };
}

export function speakersOf(t: PauditTranscript): string[] {
  return [...new Set(t.turns.map(x => x.speaker))];
}
