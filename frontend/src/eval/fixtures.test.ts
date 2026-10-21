import { expect, it } from "vitest";
import schema from "@eval-api/eval-api.schema.json";
import { fixtureCases, fixtureResponseErrors } from "./fixtureCases";
import runs from "./fixtures/runs.json";

const bodies = import.meta.glob("./fixtures/**/*.json", { eager: true, import: "default" });

it("maps every JSON body exactly once so new fixtures cannot silently escape validation", () => {
  const declared = fixtureCases.map(({ file }) => `./fixtures/${file}`);
  expect(new Set(declared).size).toBe(declared.length);
  expect(declared.sort()).toEqual(Object.keys(bodies).sort());
  expect(declared.length).toBeGreaterThan(0);
});

it("provides successful response cases for every B4 route, including D2 routes", () => {
  const routes = fixtureCases.filter(({ status }) => status < 400).map(({ route }) => route);
  expect([...new Set(routes)].sort()).toEqual(Object.keys(schema["x-routes"]).sort());
});

it.each(fixtureCases)("$file validates as $route ($status)", ({ file, route, status }) => {
  expect(fixtureResponseErrors(route, bodies[`./fixtures/${file}`], status)).toEqual([]);
});

it("covers all run states, finished failures for Resume, cross-dataset selection, and known/unknown cost", () => {
  expect([...new Set(runs.map(run => run.state))].sort()).toEqual([
    "aborted", "aborted_cost", "failed", "finished", "interrupted", "running",
  ]);
  expect(runs.some(run => run.state === "finished" && run.totals.failures > 0)).toBe(true);
  expect(runs.some(run => run.state === "finished" && run.totals.failures === 0)).toBe(true);
  expect(new Set(runs.map(run => run.dataset)).size).toBeGreaterThan(1);
  expect(runs.some(run => run.totals.cost_usd === null)).toBe(true);
  expect(runs.some(run => typeof run.totals.cost_usd === "number")).toBe(true);
});

it("covers all download states and both estimate bases", () => {
  const downloads = fixtureCases.filter(({ file }) => file.startsWith("download-"));
  expect(downloads.map(({ file }) => (bodies[`./fixtures/${file}`] as { status: string }).status).sort())
    .toEqual(["downloading", "failed", "not_downloaded", "ready"]);
  expect(bodies["./fixtures/estimate-known.json"]).toMatchObject({ basis: "prior_runs", est_cost_usd: expect.any(Number) });
  expect(bodies["./fixtures/estimate-unknown.json"]).toMatchObject({ basis: "none", est_cost_usd: null });
});

it("covers every structured API error code", () => {
  const errors = fixtureCases.filter(({ status }) => status >= 400);
  expect([...new Set(errors.map(({ file }) => (bodies[`./fixtures/${file}`] as { error: { code: string } }).error.code))].sort())
    .toEqual([...schema.$defs.Error.properties.code.enum].sort());
});

it("rejects malformed progress rather than trusting its fixture's filename", () => {
  expect(fixtureResponseErrors("GET /runs/{id}", {
    ...bodies["./fixtures/run-running.json"] as object,
    progress: { done: -1, total: 3, failures: 0, cost_usd: null },
  }).length).toBeGreaterThan(0);
});

it("rejects invalid array elements and a body assigned to the wrong route", () => {
  expect(fixtureResponseErrors("GET /runs", [{ ...runs[0], state: "invented" }]).length).toBeGreaterThan(0);
  expect(fixtureResponseErrors("GET /datasets", bodies["./fixtures/health.json"]).length).toBeGreaterThan(0);
});

it("rejects malformed error bodies rather than validating them as successful replies", () => {
  expect(fixtureResponseErrors("POST /runs", { error: { code: "invented", message: "Fictional error" } }, 409).length).toBeGreaterThan(0);
});

it("resolves nested B3 definitions in their own scope", () => {
  expect(fixtureResponseErrors("GET /runs/{id}/metrics", {
    ...bodies["./fixtures/metrics.json"] as object,
    entries: [{ metric: "accuracy", level: "item", policy: "primary", slice: {}, value: 1, n: 3, n_clusters: 3, ci: [1], ci_status: "few_clusters" }],
  }).length).toBeGreaterThan(0);
  expect(fixtureResponseErrors("GET /compare", {
    ...bodies["./fixtures/comparison.json"] as object,
    disagreements: [{ item_id: "fictional-item", cluster: "fictional-cluster", pairs: [] }],
  }).length).toBeGreaterThan(0);
});
