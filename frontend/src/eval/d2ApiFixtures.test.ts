import { expect, it, vi } from "vitest";
import { createEvalApi, type EvalApi } from "./evalApi";
import { buildLoadResult } from "./buildLoadResult";
import type { Comparison, ItemDetail, MetricsReport, RunDetail } from "./evalTypes";

const bodies = import.meta.glob("./fixtures/*.json", { eager: true, import: "default" });
const fixture = <T,>(name: string) => bodies[`./fixtures/${name}.json`] as T;
const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status });

type ApiCase = [string, (api: EvalApi) => unknown, string, string, string];
const calls: ApiCase[] = [
  ["metrics", api => api.getMetrics("saved/run"), "/runs/saved%2Frun/metrics", "GET", "metrics"],
  ["rescore", api => api.rescore("saved/run"), "/runs/saved%2Frun/rescore", "POST", "run-rescore-response"],
  ["items", api => api.listItems("saved/run", { filter: "failed", limit: 2000 }), "/runs/saved%2Frun/items?filter=failed&limit=2000", "GET", "items"],
  ["item", api => api.getItem("saved/run", "doc.1-model--2 /?#%"), "/runs/saved%2Frun/items/doc.1-model--2%20%2F%3F%23%25", "GET", "item-ok"],
  ["compare", api => api.compare("saved/run", "other&run"), "/compare?a=saved%2Frun&b=other%26run", "GET", "comparison"],
];

it.each(calls)("D2 %s returns its validated saved fixture and uses the encoded route", async (_name, call, path, method, name) => {
  const body = fixture(name);
  const fetch = vi.fn<typeof globalThis.fetch>().mockResolvedValue(json(body));
  expect(await call(createEvalApi({ fetch }))).toEqual({ ok: true, value: body });
  expect(fetch).toHaveBeenCalledWith(`/eval-api${path}`, expect.objectContaining({ method }));
});

it.each(calls)("D2 %s settles fetch rejection and preserves HTTP errors", async (name, call) => {
  const offline = createEvalApi({ fetch: vi.fn<typeof fetch>().mockRejectedValue(Error("offline")) });
  await expect(call(offline)).resolves.toEqual({ ok: false, error: { kind: "unreachable" } });
  for (const status of [404, 409]) {
    const error = { code: status === 404 ? "not_found" : "bad_state", message: "Fictional failure" };
    const api = createEvalApi({ fetch: vi.fn<typeof fetch>().mockResolvedValue(json({ error }, status)) });
    expect(await call(api)).toEqual(name === "metrics" && status === 404
      ? { ok: true, value: null }
      : { ok: false, error: { kind: "api", status, ...error } });
  }
});

it("supports the zero-shared comparison and preserves cross-dataset 409 and actual backend 422", async () => {
  const comparison = fixture<Comparison>("comparison-zero-shared");
  expect(comparison).toMatchObject({ n_shared: 0, deltas: [], disagreements: [] });
  const api = createEvalApi({ fetch: vi.fn<typeof fetch>().mockResolvedValue(json(comparison)) });
  expect(await api.compare("a", "b")).toEqual({ ok: true, value: comparison });
  for (const status of [409, 422]) {
    const body = fixture<{ error: { code: string; message: string } }>("error-cross-dataset");
    const api = createEvalApi({ fetch: vi.fn<typeof fetch>().mockResolvedValue(json(body, status)) });
    expect(await api.compare("a", "b")).toEqual({ ok: false, error: { kind: "api", status, ...body.error } });
  }
});

it("provides replayable current-contract ok and failed items with native gold", () => {
  const ok = fixture<ItemDetail>("item-ok");
  expect(buildLoadResult(ok.request, ok.response)).toMatchObject({ ok: true, value: { source: "service" } });
  expect(ok.gold_kind).toBe("tofueval_summary_sentences");
  expect(ok.gold).toMatchObject({ sentences: expect.arrayContaining([
    expect.objectContaining({ sent_idx: expect.any(Number), text: expect.any(String), label: "inconsistent", types: expect.any(Array), exp: expect.any(String), start: expect.any(Number), end: expect.any(Number) }),
  ]) });
  const failed = fixture<ItemDetail>("item-failed");
  expect(failed).toMatchObject({ status: "failed", response: null, failure: { kind: "http", http_status: 503, error_code: "backend_unreachable", message: expect.any(String), issues: expect.any(Array) }, gold_kind: "tofueval_summary_sentences" });
  expect(failed.gold).toEqual(ok.gold);
});

it("covers honest metric policies, references, grouped slices and unavailable intervals", () => {
  const metrics = fixture<MetricsReport>("metrics");
  expect(metrics.items).toMatchObject({ selected: 3, scored: 2, failed: 1 });
  expect(metrics.entries).toEqual(expect.arrayContaining([
    expect.objectContaining({ metric: "accuracy", policy: "primary", n: 3 }),
    expect.objectContaining({ metric: "accuracy", policy: "secondary", n: 2 }),
    expect.objectContaining({ metric: "failure_rate", policy: "none" }),
    expect.objectContaining({ metric: "coverage", policy: "none" }),
    expect.objectContaining({ ci_status: "few_clusters", ci: null }),
    expect.objectContaining({ ci_status: "undefined", ci: null }),
  ]));
  expect(metrics.references).toEqual(expect.arrayContaining([expect.objectContaining({ metric: "accuracy", level: "item", value: expect.any(Number) })]));
  expect(metrics.reference_caveats.length).toBeGreaterThan(0);
  expect(metrics.entries.some(entry => Object.keys(entry.slice).length > 0)).toBe(true);
});

it("provides run provenance with fingerprints, mixed warning, seed and mapping version", () => {
  const run = fixture<RunDetail>("run-finished");
  expect(run.run_info).toMatchObject({ git_commit: expect.any(String), git_dirty: true, mapping_version: expect.any(String), seed: 7, mixed: true, tags: { contamination: "fictional fixture" }, fingerprint: { models: expect.any(Object), prompt_hashes: expect.any(Object) } });
  expect(run.run_info.warnings?.length).toBeGreaterThan(0);
});
