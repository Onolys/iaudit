/**
 * Typed API client (PRD R7, D4, D8): openapi-fetch over `/v1`, bearer token
 * from a provider, `Idempotency-Key` on `POST /sessions` only, and exactly one
 * forced-refresh retry on 401 before signalling sign-out.
 */
import createClient from "openapi-fetch";
import { parseErrorBody } from "./errors";
import type { ApiPaths } from "./types";

export const DEFAULT_BASE_URL = "/v1";

/** `forceRefresh` maps to Firebase `getIdToken(true)`; null = signed out. */
export type TokenProvider = (forceRefresh?: boolean) => Promise<string | null>;

export interface ApiClientOptions {
  baseUrl?: string;
  getToken: TokenProvider;
  /** Called once when a request is still 401 after a forced token refresh. */
  onSessionExpired: () => void;
  /** Injected for tests; defaults to the global fetch. */
  fetch?: typeof fetch;
}

const IDEMPOTENCY_HEADER = "Idempotency-Key";

function isCreateSession(request: Request, baseUrl: string): boolean {
  if (request.method !== "POST") return false;
  const path = new URL(request.url, "http://localhost").pathname.replace(/\/+$/, "");
  const base = baseUrl.replace(/^https?:\/\/[^/]+/, "").replace(/\/+$/, "");
  return path === `${base}/sessions`;
}

function withToken(request: Request, token: string | null): Request {
  const next = new Request(request);
  if (token) next.headers.set("Authorization", `Bearer ${token}`);
  else next.headers.delete("Authorization");
  return next;
}

export function createApiClient(opts: ApiClientOptions) {
  const baseUrl = opts.baseUrl ?? DEFAULT_BASE_URL;
  const doFetch = opts.fetch ?? ((r: Request) => globalThis.fetch(r));

  const authedFetch = async (input: Request): Promise<Response> => {
    // The key is only meaningful on create; strip it everywhere else (R7).
    if (isCreateSession(input, baseUrl)) {
      if (!input.headers.has(IDEMPOTENCY_HEADER)) {
        input.headers.set(IDEMPOTENCY_HEADER, globalThis.crypto.randomUUID());
      }
    } else {
      input.headers.delete(IDEMPOTENCY_HEADER);
    }

    const replay = input.clone(); // body is single-use
    const first = await doFetch(withToken(input, await opts.getToken(false)));
    if (first.status !== 401) return first;

    const second = await doFetch(withToken(replay, await opts.getToken(true)));
    if (second.status === 401) opts.onSessionExpired();
    return second;
  };

  return createClient<ApiPaths>({ baseUrl, fetch: authedFetch });
}

export type ApiClient = ReturnType<typeof createApiClient>;

interface FetchResult<D> {
  data?: D;
  error?: unknown;
  response: Response;
}

/** Return `data` or throw an ApiError parsed from the `public-error-response` body. */
export function unwrap<D>(result: FetchResult<D>): D {
  if (result.response.ok) return result.data as D;
  throw parseErrorBody(result.response.status, result.error);
}
