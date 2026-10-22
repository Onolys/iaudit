import Ajv2020 from "ajv/dist/2020";
import type { ValidateFunction } from "ajv";
import schema from "@eval-api/eval-api.schema.json";
import type { Result } from "../contract";
import type { CallOpts, Comparison, DatasetMeta, DatasetSummary, DownloadStatus, ErrorResponse, Estimate, EstimateRequest, EvalError, Health, ItemDetail, ItemPage, ItemQuery, MetricsReport, ResumeRequest, RunCreated, RunDetail, RunRequest, RunSummary } from "./evalTypes";
export type { ApiCode, CallOpts, EvalError } from "./evalTypes";

type Reply<T> = Promise<Result<T, EvalError>>;
export interface EvalApi {
  health(opts?: CallOpts): Reply<Health>;
  listDatasets(opts?: CallOpts): Reply<DatasetSummary[]>;
  getDataset(name: string, opts?: CallOpts): Reply<DatasetMeta>;
  startDownload(name: string, opts?: CallOpts): Reply<DownloadStatus>;
  getDownload(name: string, opts?: CallOpts): Reply<DownloadStatus>;
  estimate(request: EstimateRequest, opts?: CallOpts): Reply<Estimate>;
  startRun(request: RunRequest, opts?: CallOpts): Reply<RunCreated>;
  listRuns(opts?: CallOpts): Reply<RunSummary[]>;
  getRun(id: string, opts?: CallOpts): Reply<RunDetail>;
  abortRun(id: string, opts?: CallOpts): Reply<RunSummary>;
  resumeRun(id: string, body?: ResumeRequest, opts?: CallOpts): Reply<RunSummary>;
  getMetrics(id: string, opts?: CallOpts): Reply<MetricsReport | null>;
  listItems(id: string, query?: ItemQuery, opts?: CallOpts): Reply<ItemPage>;
  getItem(id: string, itemId: string, opts?: CallOpts): Reply<ItemDetail>;
  rescore(id: string, opts?: CallOpts): Reply<RunSummary>;
  compare(a: string, b: string, opts?: CallOpts): Reply<Comparison>;
}
export interface EvalApiDeps { fetch: typeof fetch; baseUrl?: string }

// Nested B3 reports have their own $id and local $defs; Ajv resolves them in that scope.
const ajv = new Ajv2020({ allErrors: true, allowUnionTypes: true, strict: false });
ajv.addSchema(schema);
const validators = new Map<string, ValidateFunction>();
function validator(name: string): ValidateFunction {
  let check = validators.get(name);
  if (!check) {
    const array = name.endsWith("[]");
    const ref = `${schema.$id}#/$defs/${array ? name.slice(0, -2) : name}`;
    check = ajv.compile(array ? { type: "array", items: { $ref: ref } } : { $ref: ref });
    validators.set(name, check);
  }
  return check;
}
const badBody = (message: string): Result<never, EvalError> => ({ ok: false, error: { kind: "bad_body", message } });
const unreachable = (): Result<never, EvalError> => ({ ok: false, error: { kind: "unreachable" } });
const encode = encodeURIComponent;
/** Slow routes: abort waits for in-flight audits; compare re-scores with a bootstrap. */
const routeTimeouts: Partial<Record<keyof typeof schema["x-routes"], number>> = {
  "POST /runs/{id}/abort": 120_000,
  "GET /compare": 120_000,
};
// "." and ".." would be normalised away by URL resolution and escape the route; empty ids match nothing.
const badId = (...ids: string[]) => ids.some(id => id === "" || id === "." || id === "..");
const invalidId = (): Result<never, EvalError> => ({ ok: false, error: { kind: "api", status: 400, code: "invalid_request", message: "Invalid id" } });
const queryString = (query: Record<string, string | number | undefined>) => {
  const values = Object.entries(query).filter((entry): entry is [string, string | number] => entry[1] !== undefined);
  return values.length ? `?${values.map(([key, value]) => `${encode(key)}=${encode(String(value))}`).join("&")}` : "";
};

/** All requests, including body reads, settle on cancellation or timeout even if fetch ignores abort. */
export function createEvalApi({ fetch: doFetch, baseUrl = "/eval-api" }: EvalApiDeps): EvalApi {
  async function call<T>(route: keyof typeof schema["x-routes"], path: string | (() => string), opts: CallOpts = {}, body?: unknown, missingMetrics = false): Reply<T> {
    if (opts.signal?.aborted) return { ok: false, error: { kind: "cancelled" } };
    const method = route.startsWith("POST ") ? "POST" : "GET";
    const timeout = routeTimeouts[route] ?? (method === "POST" ? 30_000 : 10_000);
    const controller = new AbortController();
    let settleAbort!: (value: Result<T, EvalError>) => void;
    const interrupted = new Promise<Result<T, EvalError>>(resolve => { settleAbort = resolve; });
    let stopped = false;
    const abort = (error: EvalError) => {
      if (stopped) return;
      stopped = true;
      settleAbort({ ok: false, error });
      controller.abort();
    };
    const onCancel = () => abort({ kind: "cancelled" });
    opts.signal?.addEventListener("abort", onCancel);
    const timer = setTimeout(() => abort({ kind: "timeout", seconds: timeout / 1000 }), timeout);
    const perform = async (): Reply<T> => {
      try {
        const response = await doFetch(`${baseUrl.replace(/\/+$/, "")}${typeof path === "function" ? path() : path}`, {
          method, credentials: "omit", signal: controller.signal,
          headers: { Accept: "application/json", ...(body === undefined ? {} : { "Content-Type": "application/json" }) },
          ...(body === undefined ? {} : { body: JSON.stringify(body) }),
        });
        let data: unknown;
        try { data = await response.json(); }
        catch { return response.status === 502 ? unreachable() : badBody("Response is not readable JSON"); }
        if (!response.ok) {
          if (validator("ErrorResponse")(data)) {
            const { error } = data as ErrorResponse;
            if (missingMetrics && response.status === 404 && error.code === "not_found") return { ok: true, value: null as T };
            return { ok: false, error: { kind: "api", status: response.status, ...error } };
          }
          return response.status === 502 ? unreachable() : badBody("Response does not match the API error schema");
        }
        const check = validator(schema["x-routes"][route]);
        if (!check(data)) return badBody(`Response does not match ${schema["x-routes"][route]}: ${ajv.errorsText(check.errors)}`);
        return { ok: true, value: data as T };
      } catch { return unreachable(); }
    };
    try { return await Promise.race([interrupted, perform()]); }
    finally {
      stopped = true;
      clearTimeout(timer);
      opts.signal?.removeEventListener("abort", onCancel);
    }
  }
  /** Refuses unsafe ids before building a path; never throws. */
  const guard = <T,>(ids: string[], run: () => Reply<T>): Reply<T> => badId(...ids) ? Promise.resolve(invalidId()) : run();
  return {
    health: opts => call("GET /health", "/health", opts),
    listDatasets: opts => call("GET /datasets", "/datasets", opts),
    getDataset: (name, opts) => guard([name], () => call("GET /datasets/{name}", () => `/datasets/${encode(name)}`, opts)),
    startDownload: (name, opts) => guard([name], () => call("POST /datasets/{name}/download", () => `/datasets/${encode(name)}/download`, opts)),
    getDownload: (name, opts) => guard([name], () => call("GET /datasets/{name}/download", () => `/datasets/${encode(name)}/download`, opts)),
    estimate: (request, opts) => call("POST /runs/estimate", "/runs/estimate", opts, request),
    startRun: (request, opts) => call("POST /runs", "/runs", opts, request),
    listRuns: opts => call("GET /runs", "/runs", opts),
    getRun: (id, opts) => guard([id], () => call("GET /runs/{id}", () => `/runs/${encode(id)}`, opts)),
    abortRun: (id, opts) => guard([id], () => call("POST /runs/{id}/abort", () => `/runs/${encode(id)}/abort`, opts)),
    resumeRun: (id, body, opts) => guard([id], () => call("POST /runs/{id}/resume", () => `/runs/${encode(id)}/resume`, opts, body)),
    getMetrics: (id, opts) => guard([id], () => call("GET /runs/{id}/metrics", () => `/runs/${encode(id)}/metrics`, opts, undefined, true)),
    listItems: (id, query = {}, opts) => guard([id], () => call("GET /runs/{id}/items", () => `/runs/${encode(id)}/items${queryString({ filter: query.filter, limit: query.limit, offset: query.offset })}`, opts)),
    getItem: (id, itemId, opts) => guard([id, itemId], () => call("GET /runs/{id}/items/{item_id}", () => `/runs/${encode(id)}/items/${encode(itemId)}`, opts)),
    rescore: (id, opts) => guard([id], () => call("POST /runs/{id}/rescore", () => `/runs/${encode(id)}/rescore`, opts)),
    compare: (a, b, opts) => call("GET /compare", () => `/compare${queryString({ a, b })}`, opts),
  };
}
