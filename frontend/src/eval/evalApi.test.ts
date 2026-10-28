import { afterEach, expect, it, vi } from "vitest";
import { createEvalApi, type EvalApi } from "./evalApi";
const health = { status: "ok", eval_api_version: "1", backend: { url: "http://localhost", reachable: true, schema_version: null } };
const summary = { run_id: "r", dataset: "d", split: "test", n_requested: 1, n_items: 1, seed: null, created_at: "now", finished_at: null, schema_version: "0.0.1", state: "finished", score_state: "done", totals: { cost_usd: null, failures: 0 }, git_dirty: false };
const metrics = { schema_version: "1.0.0", run_id: "r", dataset: "d", dataset_version: "1", primary_policy: "p", scored: { at: "now", metrics_version: "1", git_commit: "abc", git_dirty: false }, bootstrap: { method: "bootstrap", resamples: 100, seed: 1, level: .95 }, run: { state: "finished", complete: true, mapping_version: null, tags: {} }, dataset_extra: {}, reference_caveats: [], items: { selected: 1, scored: 1, failed: 0, not_run: 0 }, failures: { by_reason: {} }, entries: [{ metric: "accuracy", level: "item", policy: "primary", slice: {}, value: 1, n: 1, n_clusters: 1, ci: [1, 1], ci_status: "few_clusters" }], references: [] };
const comparison = { schema_version: "1.0.0", run_a: "a", run_b: "b", dataset: "d", warnings: [], n_shared: 1, n_a_only: 0, n_b_only: 0, n_clusters_shared: 1, deltas: [{ metric: "accuracy", level: "item", policy: "primary", slice: {}, a: { value: 1, n: 1, ci: null }, b: { value: 0, n: 1, ci: null }, delta: -1, delta_ci: null, ci_status: "few_clusters", n_clusters: 1 }], disagreements: [{ item_id: "i", cluster: "c", pairs: [{ level: "item", unit: "u", gold: "yes", a: "yes", b: "no" }] }] };
const errorBody = (code = "not_found") => ({ error: { code, message: "probe failed", detail: { reason: "offline" } } });
const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status });
const request = { dataset: "d", split: "test", n: 3, seed: 7 };
const id = "a/b ?&";
const encoded = "a%2Fb%20%3F%26";
type RouteCase = [string, (api: EvalApi) => unknown, string, string, unknown, unknown?];
const routes: RouteCase[] = [
  ["health", a => a.health(), "/health", "GET", health],
  ["listDatasets", a => a.listDatasets(), "/datasets", "GET", [{ name: "d", product: "eaudit", title: "D", data_present: true, splits: [{ name: "test", size: null }] }]],
  ["getDataset", a => a.getDataset(id), `/datasets/${encoded}`, "GET", { name: "d", product: "eaudit", splits: [{ name: "test", size: 1, description: "test" }], description: "D", custom: true }],
  ["startDownload", a => a.startDownload(id), `/datasets/${encoded}/download`, "POST", { status: "downloading", files: [], warnings: [], error: null, updated_at: null }],
  ["getDownload", a => a.getDownload(id), `/datasets/${encoded}/download`, "GET", { status: "ready", files: [{ id: "f", filename: "f.json", sha256: "abc", size_bytes: 2, fetched_at: "now" }], warnings: [] }],
  ["estimate", a => a.estimate(request), "/runs/estimate", "POST", { basis: "none", n_items: 3, est_input_tokens: null, est_output_tokens: null, est_cost_usd: null, rough: true, note: "pilot" }, request],
  ["startRun", a => a.startRun({ ...request, max_cost_usd: 2, tags: { x: true } }), "/runs", "POST", { run_id: "r" }, { ...request, max_cost_usd: 2, tags: { x: true } }],
  ["listRuns", a => a.listRuns(), "/runs", "GET", [summary]],
  ["getRun", a => a.getRun(id), `/runs/${encoded}`, "GET", { ...summary, progress: { done: 1, total: 1, failures: 0, cost_usd: null }, run_info: { concurrency: 4, tags: {}, warnings: [] } }],
  ["abortRun", a => a.abortRun(id), `/runs/${encoded}/abort`, "POST", summary],
  ["resumeRun", a => a.resumeRun(id), `/runs/${encoded}/resume`, "POST", summary],
  ["getMetrics", a => a.getMetrics(id), `/runs/${encoded}/metrics`, "GET", metrics],
  ["listItems", a => a.listItems(id, { filter: "all", limit: 10, offset: 0 }), `/runs/${encoded}/items?filter=all&limit=10&offset=0`, "GET", { total: 1, items: [{ item_id: "i", status: "ok", gold: "yes", pred: "yes", match: true, outcome: "match", label: "yes", detail: {} }] }],
  ["getItem", a => a.getItem(id, id), `/runs/${encoded}/items/${encoded}`, "GET", { item_id: "i", status: "ok", request: {}, response: {}, failure: null, run_info: null, gold: { label: "yes" }, gold_kind: "label" }],
  ["rescore", a => a.rescore(id), `/runs/${encoded}/rescore`, "POST", summary],
  ["compare", a => a.compare(id, "c=d/#"), `/compare?a=${encoded}&b=c%3Dd%2F%23`, "GET", comparison],
];
afterEach(() => vi.useRealTimers());
it.each(routes)("%s sends correct route/body and validates B4 response", async (_name, call, path, method, body, payload) => {
  const f = vi.fn<typeof fetch>().mockResolvedValue(json(body));
  expect(await call(createEvalApi({ fetch: f }))).toEqual({ ok: true, value: body });
  expect(f).toHaveBeenCalledWith(`/eval-api${path}`, expect.objectContaining({ method, credentials: "omit", signal: expect.any(AbortSignal), headers: expect.objectContaining({ Accept: "application/json" }) }));
  expect(f.mock.calls[0][1]?.body).toBe(payload === undefined ? undefined : JSON.stringify(payload));
  if (payload !== undefined) expect(f.mock.calls[0][1]?.headers).toEqual(expect.objectContaining({ "Content-Type": "application/json" }));
});
it.each(routes)("%s rejects structurally invalid success", async (_name, call) => {
  expect(await call(createEvalApi({ fetch: vi.fn<typeof fetch>().mockResolvedValue(json({})) }))).toMatchObject({ ok: false, error: { kind: "bad_body" } });
});
it("uses custom base and omits absent query values", async () => {
  const f = vi.fn<typeof fetch>().mockResolvedValue(json({ total: 0, items: [] }));
  await createEvalApi({ fetch: f, baseUrl: "/custom/" }).listItems("r");
  expect(f.mock.calls[0][0]).toBe("/custom/runs/r/items");
});
it.each(["invalid_request", "not_found", "run_active", "bad_state", "data_missing", "backend_unreachable", "schema_mismatch", "forbidden", "internal_error"])("preserves structured API error %s including 502", async code => {
  expect(await createEvalApi({ fetch: vi.fn<typeof fetch>().mockImplementation(async () => json(errorBody(code), 502)) }).health()).toEqual({ ok: false, error: { kind: "api", status: 502, ...errorBody(code).error } });
});
it("only metrics 404 not_found succeeds with null", async () => {
  const api = createEvalApi({ fetch: vi.fn<typeof fetch>().mockImplementation(async () => json(errorBody(), 404)) });
  expect(await api.getMetrics("r")).toEqual({ ok: true, value: null });
  expect(await api.getRun("r")).toMatchObject({ ok: false, error: { kind: "api", code: "not_found" } });
  expect(await createEvalApi({ fetch: vi.fn<typeof fetch>().mockResolvedValue(json(errorBody("bad_state"), 404)) }).getMetrics("r")).toMatchObject({ ok: false, error: { kind: "api", code: "bad_state" } });
});
it.each([new Response("Bad gateway", { status: 502 }), json(errorBody("unknown"), 502)])("maps unstructured proxy 502 to unreachable", async response => {
  expect(await createEvalApi({ fetch: vi.fn<typeof fetch>().mockImplementation(async () => response.clone()) }).health()).toEqual({ ok: false, error: { kind: "unreachable" } });
});
it.each([new Response("not json"), json(null), json(errorBody("unknown"), 400), new Response("bad", { status: 400 })])("rejects non-JSON or invalid error/success", async response => {
  expect(await createEvalApi({ fetch: vi.fn<typeof fetch>().mockResolvedValue(response) }).health()).toMatchObject({ ok: false, error: { kind: "bad_body" } });
});
it("never throws for rejected or synchronous fetch errors", async () => {
  for (const f of [vi.fn<typeof fetch>().mockRejectedValue(Error("offline")), vi.fn<typeof fetch>(() => { throw Error("offline"); })]) {
    expect(await createEvalApi({ fetch: f }).health()).toEqual({ ok: false, error: { kind: "unreachable" } });
  }
});
it("never throws if JSON reading rejects", async () => {
  const response = json(health);
  vi.spyOn(response, "json").mockRejectedValue(Error("read"));
  expect(await createEvalApi({ fetch: vi.fn<typeof fetch>().mockResolvedValue(response) }).health()).toMatchObject({ ok: false, error: { kind: "bad_body" } });
});
it("already aborted signal prevents fetch", async () => {
  const f = vi.fn<typeof fetch>();
  expect(await createEvalApi({ fetch: f }).health({ signal: AbortSignal.abort() })).toEqual({ ok: false, error: { kind: "cancelled" } });
  expect(f).not.toHaveBeenCalled();
});
it.each([false, true])("timeout resolves when fetch ignores abort (POST=%s)", async post => {
  vi.useFakeTimers();
  const f = vi.fn<typeof fetch>(() => new Promise(() => {}));
  const api = createEvalApi({ fetch: f });
  const pending = post ? api.startRun(request) : api.health();
  await vi.advanceTimersByTimeAsync(post ? 30_000 : 10_000);
  expect(await pending).toEqual({ ok: false, error: { kind: "timeout", seconds: post ? 30 : 10 } });
  expect(f.mock.calls[0][1]?.signal?.aborted).toBe(true);
  expect(vi.getTimerCount()).toBe(0);
});
it("external cancellation cleans listeners and consumes late fetch rejection", async () => {
  vi.useFakeTimers();
  const controller = new AbortController();
  const remove = vi.spyOn(controller.signal, "removeEventListener");
  let reject!: (e: Error) => void;
  const f = vi.fn<typeof fetch>(() => new Promise((_resolve, r) => { reject = r; }));
  const pending = createEvalApi({ fetch: f }).health({ signal: controller.signal });
  controller.abort();
  expect(await pending).toEqual({ ok: false, error: { kind: "cancelled" } });
  expect(remove).toHaveBeenCalledWith("abort", expect.any(Function));
  expect(vi.getTimerCount()).toBe(0);
  reject(Error("late"));
  await Promise.resolve();
});
it("cleans timers/listeners on success", async () => {
  vi.useFakeTimers();
  const controller = new AbortController();
  const remove = vi.spyOn(controller.signal, "removeEventListener");
  await createEvalApi({ fetch: vi.fn<typeof fetch>().mockResolvedValue(json(health)) }).health({ signal: controller.signal });
  expect(remove).toHaveBeenCalledWith("abort", expect.any(Function));
  expect(vi.getTimerCount()).toBe(0);
});
it("preserves mismatch filter expected by server", async () => {
  const f = vi.fn<typeof fetch>().mockResolvedValue(json({ total: 0, items: [] }));
  await createEvalApi({ fetch: f }).listItems("r", { filter: "mismatch", offset: 20 });
  expect(f.mock.calls[0][0]).toBe("/eval-api/runs/r/items?filter=mismatch&offset=20");
});
it("never throws on an unencodable identifier or unserializable body", async () => {
  const f = vi.fn<typeof fetch>();
  const api = createEvalApi({ fetch: f });
  await expect(api.getRun("\uD800")).resolves.toMatchObject({ ok: false });
  const tags: Record<string, unknown> = {};
  tags.self = tags;
  await expect(api.startRun({ ...request, tags })).resolves.toMatchObject({ ok: false });
  expect(f).not.toHaveBeenCalled();
});
it("timeout also bounds response body reads and consumes their late rejection", async () => {
  vi.useFakeTimers();
  const response = json(health);
  let reject!: (e: Error) => void;
  vi.spyOn(response, "json").mockImplementation(() => new Promise((_resolve, r) => { reject = r; }));
  const pending = createEvalApi({ fetch: vi.fn<typeof fetch>().mockResolvedValue(response) }).health();
  await vi.advanceTimersByTimeAsync(10_000);
  expect(await pending).toEqual({ ok: false, error: { kind: "timeout", seconds: 10 } });
  reject(Error("late body failure"));
  await Promise.resolve();
});
it.each([
  ["metrics", { ...metrics, entries: [{ ...metrics.entries[0], ci: [1] }] }],
  ["comparison", { ...comparison, disagreements: [{ ...comparison.disagreements[0], pairs: [] }] }],
])("validates nested B3 %s definitions in their own schema scope", async (kind, body) => {
  const api = createEvalApi({ fetch: vi.fn<typeof fetch>().mockResolvedValue(json(body)) });
  expect(await (kind === "metrics" ? api.getMetrics("r") : api.compare("a", "b"))).toMatchObject({ ok: false, error: { kind: "bad_body" } });
});

it("gives GET /compare 120 s and leaves other GET routes at 10 s", async () => {
  vi.useFakeTimers();
  const hang = () => vi.fn<typeof fetch>(() => new Promise<Response>(() => {}));
  const compareResult = createEvalApi({ fetch: hang() }).compare("a", "b");
  const healthResult = createEvalApi({ fetch: hang() }).health();
  await vi.advanceTimersByTimeAsync(10_001);
  expect(await healthResult).toEqual({ ok: false, error: { kind: "timeout", seconds: 10 } });
  await vi.advanceTimersByTimeAsync(100_000);
  await vi.advanceTimersByTimeAsync(10_000);
  expect(await compareResult).toEqual({ ok: false, error: { kind: "timeout", seconds: 120 } });
});
it("gives abort 120 s and other POST routes 30 s", async () => {
  vi.useFakeTimers();
  const hang = () => vi.fn<typeof fetch>(() => new Promise<Response>(() => {}));
  const abortResult = createEvalApi({ fetch: hang() }).abortRun("r");
  const rescoreResult = createEvalApi({ fetch: hang() }).rescore("r");
  await vi.advanceTimersByTimeAsync(30_001);
  expect(await rescoreResult).toEqual({ ok: false, error: { kind: "timeout", seconds: 30 } });
  await vi.advanceTimersByTimeAsync(90_000);
  expect(await abortResult).toEqual({ ok: false, error: { kind: "timeout", seconds: 120 } });
});
it.each(["", ".", ".."])("refuses id %j before any request, without throwing", async bad => {
  const f = vi.fn<typeof fetch>();
  const api = createEvalApi({ fetch: f });
  const refused = { ok: false, error: { kind: "api", status: 400, code: "invalid_request", message: expect.stringContaining("id") } };
  for (const call of [api.getRun(bad), api.abortRun(bad), api.resumeRun(bad), api.getMetrics(bad), api.listItems(bad), api.getItem("r", bad), api.getItem(bad, "i"), api.rescore(bad), api.getDataset(bad), api.getDownload(bad), api.startDownload(bad)])
    expect(await call).toMatchObject(refused);
  expect(f).not.toHaveBeenCalled();
});
it("sends an optional resume body: absent keeps cap, null clears it", async () => {
  const f = vi.fn<typeof fetch>().mockImplementation(async () => json(summary));
  const api = createEvalApi({ fetch: f });
  await api.resumeRun("r"); await api.resumeRun("r", { max_cost_usd: null }, {});
  expect(f.mock.calls[0][1]?.body).toBeUndefined();
  expect(f.mock.calls[1][1]?.body).toBe(JSON.stringify({ max_cost_usd: null }));
});

it.each([500, 502, 503, 504, 599])("GET retries HTTP %s after 300ms even with invalid body", async status => {
  vi.useFakeTimers();
  const f = vi.fn<typeof fetch>().mockResolvedValueOnce(new Response("not JSON", { status })).mockResolvedValueOnce(json(health));
  const pending = createEvalApi({ fetch: f }).health();
  await vi.advanceTimersByTimeAsync(299);
  expect(f).toHaveBeenCalledTimes(1);
  await vi.advanceTimersByTimeAsync(1);
  expect(await pending).toEqual({ ok: true, value: health });
  expect(f).toHaveBeenCalledTimes(2);
});
it.each([400, 404, 408, 429])("GET never retries HTTP %s", async status => {
  const f = vi.fn<typeof fetch>().mockImplementation(async () => json(errorBody("invalid_request"), status));
  expect(await createEvalApi({ fetch: f }).health()).toMatchObject({ ok: false, error: { status } });
  expect(f).toHaveBeenCalledTimes(1);
});
it.each([new TypeError("offline"), new DOMException("timed out", "TimeoutError")])("GET retries transport failure %s", async error => {
  vi.useFakeTimers();
  const f = vi.fn<typeof fetch>().mockRejectedValueOnce(error).mockResolvedValueOnce(json(health));
  const pending = createEvalApi({ fetch: f }).health();
  await vi.advanceTimersByTimeAsync(300);
  expect(await pending).toEqual({ ok: true, value: health });
  expect(f).toHaveBeenCalledTimes(2);
});
it("GET stops after two network failures", async () => {
  vi.useFakeTimers();
  const f = vi.fn<typeof fetch>().mockRejectedValue(new TypeError("offline"));
  const pending = createEvalApi({ fetch: f }).health();
  await vi.advanceTimersByTimeAsync(300);
  expect(await pending).toEqual({ ok: false, error: { kind: "unreachable" } });
  expect(f).toHaveBeenCalledTimes(2);
});
it("GET cancellation interrupts retry delay", async () => {
  vi.useFakeTimers();
  const f = vi.fn<typeof fetch>().mockRejectedValue(new TypeError("offline"));
  const controller = new AbortController();
  const pending = createEvalApi({ fetch: f }).health({ signal: controller.signal });
  await vi.advanceTimersByTimeAsync(100);
  controller.abort();
  expect(await pending).toEqual({ ok: false, error: { kind: "cancelled" } });
  expect(f).toHaveBeenCalledTimes(1);
  expect(vi.getTimerCount()).toBe(0);
});
it("GET shares its existing overall deadline across retries", async () => {
  vi.useFakeTimers();
  const f = vi.fn<typeof fetch>().mockImplementationOnce(async () => {
    await new Promise(resolve => setTimeout(resolve, 9_500));
    throw new TypeError("offline");
  }).mockImplementation(() => new Promise(() => {}));
  const pending = createEvalApi({ fetch: f }).health();
  await vi.advanceTimersByTimeAsync(10_000);
  expect(await pending).toEqual({ ok: false, error: { kind: "timeout", seconds: 10 } });
  expect(f).toHaveBeenCalledTimes(2);
  expect(vi.getTimerCount()).toBe(0);
});
it.each([429, 503])("eval POST never retries HTTP %s", async status => {
  const f = vi.fn<typeof fetch>().mockImplementation(async () => json(errorBody("internal_error"), status));
  expect(await createEvalApi({ fetch: f }).startRun(request)).toMatchObject({ ok: false, error: { status } });
  expect(f).toHaveBeenCalledTimes(1);
});
