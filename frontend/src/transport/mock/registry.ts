import type { AuditRequest, Result } from "../../contract";
import type { LoadError } from "../errors";

export const MOCK_DELAY_MS = 250;

type Loader = () => Promise<string>;

export interface MockPair {
  name: string;
  loadRequest?: Loader;
  loadResponse?: Loader;
}

const FIXTURE = /^(?:(.+)\.)?(request|response)\.json$/;

/** `request.json` / `response.json` are the pair `default`; `<name>.request.json` pairs with `<name>.response.json`. */
export function parseFixtureName(path: string): { name: string; kind: "request" | "response" } | null {
  const m = FIXTURE.exec(path.slice(path.lastIndexOf("/") + 1));
  if (!m) return null;
  return { name: m[1] ?? "default", kind: m[2] as "request" | "response" };
}

export function buildRegistry(files: Record<string, Loader>): MockPair[] {
  const pairs = new Map<string, MockPair>();
  for (const [path, load] of Object.entries(files)) {
    const parsed = parseFixtureName(path);
    if (!parsed) continue;
    const pair = pairs.get(parsed.name) ?? { name: parsed.name };
    if (parsed.kind === "request") pair.loadRequest = load;
    else pair.loadResponse = load;
    pairs.set(parsed.name, pair);
  }
  return [...pairs.values()];
}

// Lazy: fixtures become separate chunks that a real-service session never fetches.
export const defaultRegistry = buildRegistry(
  import.meta.glob("../../../../docs/contracts/examples/*.json", { query: "?raw", import: "default" }) as Record<string, Loader>,
);

function delay(ms: number, signal: AbortSignal): Promise<boolean> {
  return new Promise((resolve) => {
    if (signal.aborted) return resolve(false);
    const onAbort = () => {
      clearTimeout(timer);
      resolve(false);
    };
    const timer = setTimeout(() => {
      signal.removeEventListener("abort", onAbort);
      resolve(true);
    }, ms);
    signal.addEventListener("abort", onAbort, { once: true });
  });
}

function requestIdOf(text: string): string | undefined {
  try {
    const id = (JSON.parse(text) as { request_id?: unknown }).request_id;
    return typeof id === "string" ? id : undefined;
  } catch {
    return undefined;
  }
}

/** Resolves to the response body text of the pair whose request has the same `request_id`. */
export async function lookupMock(
  request: AuditRequest,
  opts: { registry: MockPair[]; signal: AbortSignal; delayMs?: number },
): Promise<Result<string, LoadError>> {
  if (!(await delay(opts.delayMs ?? MOCK_DELAY_MS, opts.signal))) {
    return { ok: false, error: { kind: "cancelled" } };
  }
  const id = request.request_id;
  if (id !== undefined) {
    for (const pair of opts.registry) {
      if (!pair.loadRequest || !pair.loadResponse) continue;
      if (requestIdOf(await pair.loadRequest()) === id) {
        return { ok: true, value: await pair.loadResponse() };
      }
    }
  }
  return { ok: false, error: { kind: "mock_no_match", requestId: id } };
}
