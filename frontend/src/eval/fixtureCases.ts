import Ajv2020 from "ajv/dist/2020";
import type { ValidateFunction } from "ajv";
import schema from "@eval-api/eval-api.schema.json";

export type FixtureRoute = keyof typeof schema["x-routes"];
export interface FixtureCase { file: string; route: FixtureRoute; status: number }

// Shared D1/D2 fake-fetch cases. Bodies use fictional data and the public contract example.
export const fixtureCases: FixtureCase[] = [
  { file: "comparison-zero-shared.json", route: "GET /compare", status: 200 },
  { file: "error-cross-dataset.json", route: "GET /compare", status: 409 },
  { file: "comparison.json", route: "GET /compare", status: 200 },
  { file: "dataset-detail.json", route: "GET /datasets/{name}", status: 200 },
  { file: "datasets-empty.json", route: "GET /datasets", status: 200 },
  { file: "datasets.json", route: "GET /datasets", status: 200 },
  { file: "download-downloading.json", route: "POST /datasets/{name}/download", status: 202 },
  { file: "download-failed.json", route: "GET /datasets/{name}/download", status: 200 },
  { file: "download-not-downloaded.json", route: "GET /datasets/{name}/download", status: 200 },
  { file: "download-ready.json", route: "GET /datasets/{name}/download", status: 200 },
  { file: "error-backend-unreachable.json", route: "POST /runs", status: 502 },
  { file: "error-bad-state.json", route: "POST /runs", status: 409 },
  { file: "error-data-missing.json", route: "POST /runs", status: 409 },
  { file: "error-forbidden.json", route: "POST /runs", status: 403 },
  { file: "error-internal-error.json", route: "POST /runs", status: 500 },
  { file: "error-invalid-request.json", route: "POST /runs", status: 422 },
  { file: "error-not-found.json", route: "POST /runs", status: 404 },
  { file: "error-run-active.json", route: "POST /runs", status: 409 },
  { file: "error-schema-mismatch.json", route: "POST /runs", status: 409 },
  { file: "estimate-known.json", route: "POST /runs/estimate", status: 200 },
  { file: "estimate-unknown.json", route: "POST /runs/estimate", status: 200 },
  { file: "health-backend-unreachable.json", route: "GET /health", status: 200 },
  { file: "health.json", route: "GET /health", status: 200 },
  { file: "item-failed.json", route: "GET /runs/{id}/items/{item_id}", status: 200 },
  { file: "item-ok.json", route: "GET /runs/{id}/items/{item_id}", status: 200 },
  { file: "item-unmapped.json", route: "GET /runs/{id}/items/{item_id}", status: 200 },
  { file: "items-empty.json", route: "GET /runs/{id}/items", status: 200 },
  { file: "items.json", route: "GET /runs/{id}/items", status: 200 },
  { file: "metrics.json", route: "GET /runs/{id}/metrics", status: 200 },
  { file: "run-abort-response.json", route: "POST /runs/{id}/abort", status: 200 },
  { file: "run-aborted.json", route: "GET /runs/{id}", status: 200 },
  { file: "run-aborted_cost.json", route: "GET /runs/{id}", status: 200 },
  { file: "run-created.json", route: "POST /runs", status: 202 },
  { file: "run-failed.json", route: "GET /runs/{id}", status: 200 },
  { file: "run-finished-with-failures.json", route: "GET /runs/{id}", status: 200 },
  { file: "run-finished.json", route: "GET /runs/{id}", status: 200 },
  { file: "run-interrupted.json", route: "GET /runs/{id}", status: 200 },
  { file: "run-rescore-response.json", route: "POST /runs/{id}/rescore", status: 202 },
  { file: "run-resume-response.json", route: "POST /runs/{id}/resume", status: 202 },
  { file: "run-running.json", route: "GET /runs/{id}", status: 200 },
  { file: "runs-empty.json", route: "GET /runs", status: 200 },
  { file: "runs.json", route: "GET /runs", status: 200 },
];

// Add the whole schema so embedded B3 $id/$defs references retain their scope.
const ajv = new Ajv2020({ allErrors: true, allowUnionTypes: true, strict: false });
ajv.addSchema(schema);
const validators = new Map<string, ValidateFunction>();

/** Returns schema errors, or an empty list for a valid response body.
 * Uses x-routes for success bodies and ErrorResponse for HTTP error bodies.
 * D2 tests may reuse this helper for their own fake-fetch response cases.
 */
export function fixtureResponseErrors(route: FixtureRoute, body: unknown, status = 200): string[] {
  const name = status >= 400 ? "ErrorResponse" : schema["x-routes"][route];
  let validate = validators.get(name);
  if (!validate) {
    const array = name.endsWith("[]");
    const ref = { $ref: `${schema.$id}#/$defs/${array ? name.slice(0, -2) : name}` };
    validate = ajv.compile(array ? { type: "array", items: ref } : ref);
    validators.set(name, validate);
  }
  if (validate(body)) return [];
  return (validate.errors ?? []).map(error => `${error.instancePath || "/"}: ${error.message}`);
}
